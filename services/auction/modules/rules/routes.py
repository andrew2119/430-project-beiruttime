from uuid import UUID
from fastapi import APIRouter, Query, Request
from bt_contracts.auction.core.models import AuctionRules, CreateAuction
from bt_contracts_core.errors import PublicError
from service_app.engine import public_lot

router = APIRouter()


@router.post('/v1/auctions')
async def create(command: CreateAuction, request: Request):
    return await request.app.state.auction.create(request, command)


@router.patch('/v1/auctions/{auction_id}/rules')
async def update(auction_id: UUID, command: AuctionRules, request: Request):
    return await request.app.state.auction.update_rules(request, auction_id, command)


@router.get('/v1/auctions')
async def list_auctions(request: Request, listing_id: UUID | None = None,
                        limit: int = Query(default=30, ge=1, le=100)):
    async with request.app.state.pool.acquire() as tx:
        now = await tx.fetchval('SELECT clock_timestamp()')
        rows = await tx.fetch('''SELECT * FROM auction_lots WHERE ($1::uuid IS NULL OR listing_id=$1)
            ORDER BY created_at DESC,id LIMIT $2''', listing_id, limit)
        return {'items': [public_lot(row, now) for row in rows], 'server_time': now.isoformat()}


@router.get('/v1/seller/auctions')
async def seller_auctions(request: Request, limit: int = Query(default=30, ge=1, le=100)):
    from bt_runtime.principal import require_scope
    principal = await request.app.state.auction.dependencies.principal(request)
    require_scope(principal, 'identity.listings.publish', principal.actor.organization_id)
    async with request.app.state.pool.acquire() as tx:
        now = await tx.fetchval('SELECT clock_timestamp()')
        rows = await tx.fetch('''SELECT * FROM auction_lots WHERE
            (seller_organization_id IS NULL AND seller_id=$1 AND $2::uuid IS NULL)
            OR (seller_organization_id=$2) ORDER BY created_at DESC,id LIMIT $3''',
            principal.actor.subject_id, principal.actor.organization_id, limit)
        return {'items': [{**public_lot(row, now), 'reserve_minor': row['reserve_minor']} for row in rows],
            'server_time': now.isoformat()}


@router.get('/v1/auctions/{auction_id}')
async def get(auction_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
        if not lot:
            raise PublicError('not_found', 'Auction not found.', status=404)
        return public_lot(lot, await tx.fetchval('SELECT clock_timestamp()'))
