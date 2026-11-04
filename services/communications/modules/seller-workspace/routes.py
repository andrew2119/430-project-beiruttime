"""CP P-15: source-owned sections fail independently, never invented balances."""

import asyncio
import os
from uuid import UUID
from fastapi import APIRouter, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import PublicError
from bt_runtime.principal import CurrentPrincipal, current_principal, require_scope

router = APIRouter()


def clients(app):
    if not hasattr(app.state, "seller_workspace_clients"):
        app.state.seller_workspace_clients = {
            name: DependencyClient(
                name, os.getenv(name.upper() + "_URL", f"http://{name}:8000"), timeout=1.5, concurrency=3
            )
            for name in ("identity", "catalog", "auction", "orders")
        }
    return app.state.seller_workspace_clients


async def manage_clients(app, stop):
    owned = clients(app)
    try:
        await stop.wait()
    finally:
        await asyncio.gather(*(client.aclose() for client in owned.values()))


@router.get("/v1/seller/workspace")
async def workspace(request: Request):
    token = request.headers.get("Authorization", "")
    if not token.startswith("Bearer ") or len(token) > 8192:
        raise PublicError("unauthorized", "Sign in to continue.", status=401)
    selected = request.query_params.get("organization_id")
    if selected:
        try:
            selected = str(UUID(selected))
        except ValueError:
            raise PublicError("invalid_organization", "Choose a valid organization.", status=422) from None
        response = await clients(request.app)["identity"].request(
            "GET",
            "/internal/v1/principal",
            params={"organization_id": selected},
            headers={"Authorization": token, "X-Request-ID": request.state.request_id},
        )
        if isinstance(response, Unavailable):
            person = response
        elif response.status_code != 200:
            raise PublicError("forbidden", "Access denied.", status=403)
        else:
            person = CurrentPrincipal.model_validate(response.json())
            if str(person.actor.organization_id) != selected:
                raise PublicError("forbidden", "Access denied.", status=403)
    else:
        person = await current_principal(clients(request.app)["identity"], token[7:], request.state.request_id)
    if isinstance(person, Unavailable):
        raise PublicError("identity_unavailable", "Identity is temporarily unavailable.", status=503)
    if person.actor.organization_id:
        require_scope(person, "business.stock.write", person.actor.organization_id)

    async def section(service, path):
        response = await clients(request.app)[service].request(
            "GET",
            path,
            params={"organization_id": str(person.actor.organization_id)} if person.actor.organization_id else {},
            headers={"Authorization": token, "X-Request-ID": request.state.request_id},
        )
        if isinstance(response, Unavailable) or response.status_code != 200:
            return {"status": "unavailable"}
        try:
            data = response.json()
        except ValueError:
            return {"status": "unavailable"}
        return {"status": "available", "data": data}

    listings, bids, sales = await asyncio.gather(
        section("catalog", "/v1/seller/listings?limit=30"),
        section("auction", "/v1/seller/auctions"),
        section("orders", "/v1/orders"),
    )

    def valid_id(value):
        try:
            return isinstance(value, str) and str(UUID(value)) == value
        except ValueError:
            return False

    if bids["status"] == "available":
        records = bids["data"].get("items") if isinstance(bids["data"], dict) else None
        if not isinstance(records, list) or any(
            not isinstance(item, dict)
            or type(item.get("accepted_sequence")) is not int
            or item["accepted_sequence"] < 0
            or not valid_id(item.get("id"))
            or not valid_id(item.get("listing_id"))
            or type(item.get("current_minor")) is not int
            or item["current_minor"] < 0
            or item.get("currency") not in ("USD", "LBP")
            or item.get("status") not in ("live", "scheduled", "ended")
            for item in records
        ):
            bids = {"status": "unavailable"}
        else:
            # Closed seller projection: confidential reserve/maxima are not part
            # of this workspace, even though the source owner permits reserve reads.
            fields = ("id", "listing_id", "current_minor", "currency", "accepted_sequence", "status")
            bids = {
                "status": "available",
                "data": {"items": [{field: item.get(field) for field in fields} for item in records[:50]]},
            }
    if sales["status"] == "available":
        records = sales["data"].get("items") if isinstance(sales["data"], dict) else None
        if not isinstance(records, list) or any(
            not isinstance(item, dict) or not valid_id(item.get("seller_id")) or "organization_id" not in item
            for item in records
        ):
            sales = {"status": "unavailable"}
        else:
            own = [
                item
                for item in records
                if isinstance(item, dict)
                and (
                    str(item.get("organization_id")) == str(person.actor.organization_id)
                    if person.actor.organization_id
                    else item.get("organization_id") is None and item.get("seller_id") == str(person.actor.subject_id)
                )
            ]
            if any(
                item.get("state") not in ("awaiting_payment", "payment_unknown", "expired_fenced")
                or not valid_id(item.get("id"))
                or not valid_id(item.get("watch_id"))
                or type(item.get("revision")) is not int
                or item["revision"] < 1
                for item in own
            ):
                sales = {"status": "unavailable"}
            else:
                fields = ("id", "watch_id", "state", "revision", "deadline")
                sales = {
                    "status": "available",
                    "data": {"items": [{field: item.get(field) for field in fields} for item in own[:50]]},
                }
    return {
        "listings": listings,
        "bids": bids,
        "sales": sales,
        "payout": {
            "status": "not_available",
            "reason": "No confirmed payment, receipt and release outcome has been recorded.",
        },
    }
