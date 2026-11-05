"""Explicit v2 public projection; v1 exact DTOs remain consumable unchanged."""
from uuid import UUID
from fastapi import APIRouter, Query, Request
from bt_contracts_core.errors import PublicError
from service_app.engine import mask, public_lot

router = APIRouter()


@router.get('/v2/auctions')
async def listing(request: Request, listing_id: UUID | None = None, limit: int = Query(default=30, ge=1, le=100)):
    async with request.app.state.pool.acquire() as tx:
        now = await tx.fetchval('SELECT clock_timestamp()')
        rows = await tx.fetch('''SELECT * FROM auction_lots WHERE ($1::uuid IS NULL OR listing_id=$1)
            ORDER BY created_at DESC,id LIMIT $2''', listing_id, limit)
    return {'version': 2, 'items': [public_lot(row, now, version=2) for row in rows], 'server_time': now.isoformat()}


@router.get('/v2/auctions/{auction_id}')
async def read(auction_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
        if lot is None:
            raise PublicError('not_found', 'Auction not found.', status=404)
        return public_lot(lot, await tx.fetchval('SELECT clock_timestamp()'), version=2)


@router.get('/v2/auctions/{auction_id}/history')
async def history(auction_id: UUID, request: Request, after_sequence: int = Query(default=0, ge=0),
                  limit: int = Query(default=50, ge=1, le=100)):
    async with request.app.state.pool.acquire() as tx:
        async with tx.transaction(isolation='repeatable_read', readonly=True):
            lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
            if lot is None:
                raise PublicError('not_found', 'Auction not found.', status=404)
            rows = await tx.fetch('''SELECT sequence,bidder_id,amount_minor,automatic,received_at FROM auction_bids
                WHERE auction_id=$1 AND sequence>$2 ORDER BY sequence LIMIT $3''', auction_id, after_sequence, limit + 1)
            items = [{'sequence': row['sequence'], 'bidder': mask(auction_id, row['bidder_id']),
                'amount_minor': row['amount_minor'], 'automatic': row['automatic'],
                'received_at': row['received_at'].isoformat()} for row in rows[:limit]]
            return {'version': 2, 'items': items, 'has_more': len(rows) > limit,
                'next_sequence': items[-1]['sequence'] if items else after_sequence,
                'snapshot': public_lot(lot, await tx.fetchval('SELECT clock_timestamp()'), version=2)}
