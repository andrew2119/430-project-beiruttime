from uuid import UUID
from fastapi import APIRouter, Query, Request
from bt_contracts.auction.core.models import BidCommand
from bt_contracts_core.errors import PublicError
from service_app.engine import decoded, mask, public_lot

router = APIRouter()


@router.post('/v1/auctions/{auction_id}/bids')
async def bid(auction_id: UUID, command: BidCommand, request: Request):
    return await request.app.state.auction.submit(request, auction_id, command)


@router.get('/v1/auctions/{auction_id}/history')
async def history(auction_id: UUID, request: Request, after_sequence: int = Query(default=0, ge=0),
                  limit: int = Query(default=50, ge=1, le=100)):
    async with request.app.state.pool.acquire() as tx:
        async with tx.transaction(isolation='repeatable_read', readonly=True):
            lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
            if not lot:
                raise PublicError('not_found', 'Auction not found.', status=404)
            rows = await tx.fetch('''SELECT sequence,bidder_id,amount_minor,automatic,received_at FROM auction_bids
                WHERE auction_id=$1 AND sequence>$2 ORDER BY sequence LIMIT $3''', auction_id, after_sequence, limit + 1)
            items = [{'sequence': row['sequence'], 'bidder': mask(auction_id, row['bidder_id']),
                'amount_minor': row['amount_minor'], 'automatic': row['automatic'],
                'received_at': row['received_at'].isoformat()} for row in rows[:limit]]
            return {'items': items, 'has_more': len(rows) > limit,
                'next_sequence': items[-1]['sequence'] if items else after_sequence,
                'snapshot': public_lot(lot, await tx.fetchval('SELECT clock_timestamp()'))}


async def find_operation(request, *, auction_id=None, operation_id=None, key=None):
    principal = await request.app.state.auction.dependencies.principal(request)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('''SELECT outcome FROM auction_operations WHERE subject_id=$1
            AND organization_id IS NOT DISTINCT FROM $2
            AND ($3::uuid IS NULL OR auction_id=$3) AND ($4::uuid IS NULL OR id=$4)
            AND ($5::text IS NULL OR operation_key=$5)''', principal.actor.subject_id,
            principal.actor.organization_id, auction_id, operation_id, key)
        if not row:
            raise PublicError('not_found', 'Operation not found.', status=404)
        return decoded(row['outcome'])


@router.get('/v1/auctions/{auction_id}/operations/{operation_id}')
async def operation(auction_id: UUID, operation_id: UUID, request: Request):
    return await find_operation(request, auction_id=auction_id, operation_id=operation_id)


@router.get('/v1/auction-operations/by-key/{key}')
async def by_key(key: str, request: Request):
    if len(key) > 128:
        raise PublicError('not_found', 'Operation not found.', status=404)
    return await find_operation(request, key=key)


@router.get('/v1/my-bids')
async def mine(request: Request, limit: int = Query(default=50, ge=1, le=100), cursor: UUID | None = None):
    principal = await request.app.state.auction.dependencies.principal(request)
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch('''SELECT a.* FROM auction_lots a WHERE EXISTS
            (SELECT 1 FROM auction_operations o WHERE o.auction_id=a.id AND o.subject_id=$1
             AND o.outcome->>'status'='succeeded' AND o.outcome->>'code'='bid_accepted')
             AND ($3::uuid IS NULL OR (a.ends_at,a.id)<(SELECT c.ends_at,c.id FROM auction_lots c
               WHERE c.id=$3 AND EXISTS(SELECT 1 FROM auction_operations own WHERE own.auction_id=c.id
               AND own.subject_id=$1 AND own.outcome->>'code'='bid_accepted')))
             ORDER BY a.ends_at DESC,a.id LIMIT $2''', principal.actor.subject_id, limit + 1, cursor)
        now = await tx.fetchval('SELECT clock_timestamp()')
        return {'items': [{**public_lot(row, now), 'auction_id': str(row['id']),
            'buyer_id': str(principal.actor.subject_id), 'current_price_minor': row['current_minor'],
            'my_status': 'leading' if row['leader_id'] == principal.actor.subject_id else 'outbid',
            'next_action': 'auction_ended' if now >= row['ends_at'] else 'review_bid'} for row in rows[:limit]],
            'next_cursor': str(rows[limit - 1]['id']) if len(rows) > limit else None}
