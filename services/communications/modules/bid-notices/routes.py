import os
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import PublicError
from bt_runtime.event_http import build_event_router
from bt_runtime.principal import current_principal
from .events import accepted

router = APIRouter()
router.include_router(build_event_router('L05.bid-notices', {'auction.bid-accepted.v1': ('auction', accepted)}))


def clients(request):
    # Normally installed by supervised worker before requests; also safe in isolated router tests.
    if not hasattr(request.app.state, 'bid_notice_clients'):
        request.app.state.bid_notice_clients = {name: DependencyClient(name, os.environ.get(
            f'{name.upper()}_URL', f'http://{name}:8000'), timeout=1.2, concurrency=4)
            for name in ('identity', 'auction')}
    return request.app.state.bid_notice_clients


async def owner(request):
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    principal = await current_principal(clients(request)['identity'], token, request.state.request_id)
    if isinstance(principal, Unavailable):
        raise PublicError('identity_unavailable', 'Current access cannot be verified.', status=503)
    return principal.actor.subject_id


def dto(row):
    return {'id': str(row['id']), 'kind': row['kind'], 'auction_id': str(row['auction_id']),
        'listing_id': str(row['listing_id']), 'sequence': row['sequence'], 'current_minor': row['current_minor'],
        'currency': row['currency'], 'ends_at': row['ends_at'].isoformat(),
        'created_at': row['created_at'].isoformat(), 'href': f"/watches/{row['listing_id']}",
        'inbox_delivery': 'delivered' if row['delivered_at'] else 'pending'}


@router.get('/v1/bid-notices')
async def notices(request: Request, limit: int = Query(default=30, ge=1, le=100),
                  before: UUID | None = None):
    subject = await owner(request)
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch('''SELECT * FROM bid_notices WHERE recipient_id=$1
            AND ($2::uuid IS NULL OR (created_at,id)<(SELECT created_at,id FROM bid_notices
                WHERE id=$2 AND recipient_id=$1)) ORDER BY created_at DESC,id DESC LIMIT $3''', subject, before, limit + 1)
        return {'items': [dto(row) for row in rows[:limit]], 'has_more': len(rows) > limit,
            'next_cursor': str(rows[limit - 1]['id']) if len(rows) > limit else None}


@router.get('/v1/bid-notices/{notice_id}')
async def open_notice(notice_id: UUID, request: Request):
    subject = await owner(request)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM bid_notices WHERE id=$1 AND recipient_id=$2', notice_id, subject)
    if not row:
        raise PublicError('not_found', 'Notice not found.', status=404)
    result = await clients(request)['auction'].request('GET', f"/v1/auctions/{row['auction_id']}",
        headers={'X-Request-ID': request.state.request_id})
    canonical = None
    if not isinstance(result, Unavailable) and result.status_code == 200:
        try:
            raw = result.json()
            # Strict allowlist: no private upstream fields are exposed by this consumer.
            canonical = {key: raw[key] for key in ('id', 'current_minor', 'next_minimum_minor', 'currency',
                'ends_at', 'server_time', 'revision', 'accepted_sequence', 'status')}
        except (ValueError, KeyError, TypeError):
            pass
    return {'notice': dto(row), 'current': canonical,
        'current_status': 'available' if canonical else 'unavailable', 'requires_new_fee_preview': True}
