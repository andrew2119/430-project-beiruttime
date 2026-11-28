from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Query, Request
from bt_contracts_core.errors import PublicError

router = APIRouter()


def timing(lot, now):
    return {'auction_id': str(lot['id']), 'listing_id': str(lot['listing_id']),
        'starts_at': lot['starts_at'].isoformat(), 'scheduled_ends_at': lot['scheduled_ends_at'].isoformat(),
        'current_ends_at': lot['ends_at'].isoformat(), 'server_time': now.isoformat(),
        'status': 'scheduled' if now < lot['starts_at'] else 'ended' if now >= lot['ends_at'] else 'live',
        'revision': lot['revision'], 'rules_version': lot['rules_version'],
        'extension_policy': lot['extension_policy']}


@router.get('/v1/auctions/{auction_id}/timing')
async def one(auction_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
        if not lot:
            raise PublicError('not_found', 'Auction not found.', status=404)
        return timing(lot, await tx.fetchval('SELECT clock_timestamp()'))


@router.get('/v1/auction-timing')
async def listing(request: Request, listing_ids: str | None = Query(default=None, max_length=3699),
                  status: Literal['active', 'live', 'scheduled', 'ended', 'all'] = 'active',
                  limit: int = Query(default=100, ge=1, le=100), cursor: UUID | None = None):
    ids = None
    if listing_ids is not None:
        try:
            values = listing_ids.split(',')
            if not 1 <= len(values) <= 100:
                raise ValueError()
            ids = list(dict.fromkeys(UUID(value) for value in values))
        except ValueError:
            raise PublicError('invalid_listing_ids', 'Supply at most one hundred listing references.', status=422) from None
    async with request.app.state.pool.acquire() as tx:
        async with tx.transaction(isolation='repeatable_read', readonly=True):
            now = await tx.fetchval('SELECT clock_timestamp()')
            rows = await tx.fetch('''SELECT * FROM auction_lots a WHERE
                ($1::uuid[] IS NULL OR a.listing_id=ANY($1)) AND
                ($2='all' OR ($2='active' AND a.ends_at>$3) OR
                 ($2='live' AND a.starts_at<=$3 AND a.ends_at>$3) OR
                 ($2='scheduled' AND a.starts_at>$3) OR ($2='ended' AND a.ends_at<=$3)) AND
                ($4::uuid IS NULL OR (a.ends_at,a.id)>(SELECT c.ends_at,c.id FROM auction_lots c WHERE c.id=$4))
                ORDER BY a.ends_at,a.id LIMIT $5''', ids, status, now, cursor, limit + 1)
            known = {row['listing_id'] for row in await tx.fetch(
                'SELECT listing_id FROM auction_lots WHERE listing_id=ANY($1::uuid[])', ids)} if ids is not None else set()
            return {'version': 1, 'items': [timing(row, now) for row in rows[:limit]],
                'server_time': now.isoformat(),
                'missing_listing_ids': [str(value) for value in ids or [] if value not in known],
                'next_cursor': str(rows[limit - 1]['id']) if len(rows) > limit else None}
