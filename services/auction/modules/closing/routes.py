from uuid import UUID
import jwt
from fastapi import APIRouter, Request
from bt_contracts.auction.closing import CloseAuction
from bt_contracts_core.errors import PublicError, AccessDenied
from .service import close, public

router = APIRouter(tags=["auction-close-v1"])


def service(request, allowed):
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    key = request.app.state.settings.service_auth_public_key
    if not key:
        raise PublicError(
            "service_auth_unavailable",
            "Current service authentication is unavailable.",
            status=503,
        )
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=request.app.state.settings.auth_issuer,
            audience="auction",
            options={"require": ["exp", "iat", "iss", "aud", "sub", "type"]},
        )
        if (
            scheme.lower() != "bearer"
            or claims["type"] != "service"
            or claims["sub"] not in allowed
        ):
            raise AccessDenied("Service access denied")
    except jwt.InvalidTokenError:
        raise PublicError(
            "unauthorized", "Service authentication required.", status=401
        ) from None


@router.post("/internal/v1/auctions/{auction_id}/close")
async def command(auction_id: UUID, body: CloseAuction, request: Request):
    service(request, {"auction"})
    return await close(
        request.app, auction_id, body.expected_end_version, request.state.request_id
    )


@router.get("/v1/auctions/{auction_id}/result")
async def result(auction_id: UUID, request: Request):
    row = await request.app.state.pool.fetchrow(
        "SELECT c.*,l.currency FROM l13_auction_closes c JOIN auction_lots l ON l.id=c.auction_id WHERE c.auction_id=$1",
        auction_id,
    )
    if row:
        return public(row)
    lot = await request.app.state.pool.fetchrow(
        "SELECT end_version,mode,currency FROM auction_lots WHERE id=$1", auction_id
    )
    if lot is None:
        raise PublicError("not_found", "Auction not found.", status=404)
    return {
        "auction_id": str(auction_id),
        "status": "not_closed",
        "end_version": lot["end_version"],
        "mode": lot["mode"],
        "currency": lot["currency"],
        "winner": None,
        "order_available": False,
    }


@router.get("/v1/auctions/{auction_id}/my-result")
async def mine(auction_id: UUID, request: Request):
    actor = await request.app.state.auction.dependencies.principal(request)
    if actor.actor.organization_id:
        raise AccessDenied("Use an individual buyer account")
    row = await request.app.state.pool.fetchrow(
        "SELECT c.*,l.currency FROM l13_auction_closes c JOIN auction_lots l ON l.id=c.auction_id WHERE c.auction_id=$1",
        auction_id,
    )
    if row is None:
        return {
            "auction_id": str(auction_id),
            "status": "not_closed",
            "won": False,
            "order_id": None,
        }
    won = row["winner_id"] == actor.actor.subject_id
    return public(row) | {
        "won": won,
        "order_id": str(row["order_id"]) if won and row["order_id"] else None,
    }


@router.get("/internal/v1/auctions/{auction_id}/close-result")
async def internal_result(auction_id: UUID, request: Request):
    service(request, {"communications", "pricing", "orders"})
    row = await request.app.state.pool.fetchrow(
        "SELECT c.*,l.currency FROM l13_auction_closes c JOIN auction_lots l ON l.id=c.auction_id WHERE c.auction_id=$1",
        auction_id,
    )
    if row is None:
        raise PublicError("not_found", "Close decision not found.", status=404)
    lot = await request.app.state.pool.fetchrow(
        "SELECT listing_id,watch_id,seller_id,seller_organization_id,currency FROM auction_lots WHERE id=$1",
        auction_id,
    )
    return (
        public(row)
        | {k: str(v) if isinstance(v, UUID) else v for k, v in dict(lot).items()}
        | {
            "winner_id": str(row["winner_id"]) if row["winner_id"] else None,
            "order_id": str(row["order_id"]) if row["order_id"] else None,
        }
    )
