import hashlib
import json
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Query
from bt_bulkheads import Unavailable
from bt_contracts.comms.inbox.models import NoticeMutation, Preferences
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.security import actor, idempotency

router = APIRouter(prefix='/v1/inbox', tags=['inbox'])


def project(row):
    own_link = row['recipient_id'] == row['resource_owner_id']
    return {key: (str(row[key]) if isinstance(row[key], UUID) else row[key]) for key in
        ('id','kind','resource_id','resource_revision','event_time','read_at','cleared_at','revision','required','sample')} | {
        'destination': '/v1/inbox/' + str(row['id']) + '/destination' if own_link else None}


@router.get('')
async def listing(request: Request, owner=Depends(actor), limit: int = Query(20, ge=1, le=50), cursor: UUID | None = None):
    async with request.app.state.pool.acquire() as tx:
        boundary = None
        if cursor:
            boundary = await tx.fetchrow('SELECT event_time,id FROM l07_notices WHERE id=$1 AND recipient_id=$2', cursor, owner)
            if boundary is None:
                raise PublicError('invalid_cursor', 'Restart the inbox list.', status=400)
        rows = await tx.fetch('''SELECT * FROM l07_notices WHERE recipient_id=$1 AND cleared_at IS NULL
            AND ($2::timestamptz IS NULL OR (event_time,id)<($2,$3::uuid)) ORDER BY event_time DESC,id DESC LIMIT $4''',
            owner, boundary['event_time'] if boundary else None, cursor, limit + 1)
        total = await tx.fetchval('SELECT count(*) FROM l07_notices WHERE recipient_id=$1 AND cleared_at IS NULL', owner)
        unread = await tx.fetchval('SELECT count(*) FROM l07_notices WHERE recipient_id=$1 AND read_at IS NULL AND cleared_at IS NULL', owner)
        return {'items': [project(row) for row in rows[:limit]], 'unread_count': unread, 'total_count': total,
                'next_cursor': str(rows[limit-1]['id']) if len(rows) > limit else None}


@router.get('/preferences')
async def preferences(request: Request, owner=Depends(actor)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT optional_enabled,revision FROM l07_notice_preferences WHERE owner_id=$1', owner)
        return dict(row) if row else {'optional_enabled': True, 'revision': 0}


@router.put('/preferences')
async def save_preferences(body: Preferences, request: Request, owner=Depends(actor), key=Depends(idempotency)):
    fingerprint = hashlib.sha256(f'notice-preferences:{body.optional_enabled}:{body.expected_revision}'.encode()).hexdigest()
    async with unit_of_work(request.app.state.pool, lock_key='notice-operation:' + str(owner)) as tx:
        prior = await tx.fetchrow('SELECT * FROM l07_notice_operations WHERE owner_id=$1 AND idempotency_key=$2', owner, key)
        if prior:
            if prior['request_hash'] != fingerprint:
                raise PublicError('idempotency_conflict', 'Request key fields differ.', status=409,
                    details={'en': 'Use the original action reference.', 'ar': 'استخدم مرجع الإجراء الأصلي.'})
            return json.loads(prior['result']) if isinstance(prior['result'], str) else dict(prior['result'])
        revision = await tx.fetchval('SELECT revision FROM l07_notice_preferences WHERE owner_id=$1', owner) or 0
        if revision != body.expected_revision:
            raise PublicError('stale_revision', 'Reload the current preferences.', status=409)
        await tx.execute('''INSERT INTO l07_notice_preferences VALUES($1,$2,1) ON CONFLICT(owner_id)
            DO UPDATE SET optional_enabled=$2,revision=l07_notice_preferences.revision+1''', owner, body.optional_enabled)
        result = {'optional_enabled': body.optional_enabled, 'revision': revision + 1}
        await tx.execute('INSERT INTO l07_notice_operations VALUES($1,$2,$3,$4::jsonb)',
            owner, key, fingerprint, json.dumps(result))
        return result


async def mutate(notice_id, action, body, request, owner, key):
    fingerprint = hashlib.sha256(f'{notice_id}:{action}:{body.expected_revision}'.encode()).hexdigest()
    async with unit_of_work(request.app.state.pool, lock_key='notice-operation:' + str(owner)) as tx:
        prior = await tx.fetchrow('SELECT * FROM l07_notice_operations WHERE owner_id=$1 AND idempotency_key=$2', owner, key)
        if prior:
            if prior['request_hash'] != fingerprint:
                raise PublicError('idempotency_conflict', 'Request key fields differ.', status=409)
            return json.loads(prior['result'])
        row = await tx.fetchrow('SELECT * FROM l07_notices WHERE id=$1 AND recipient_id=$2 FOR UPDATE', notice_id, owner)
        if row is None:
            raise PublicError('not_found', 'Notice not found.', status=404)
        if row['revision'] != body.expected_revision:
            raise PublicError('stale_revision', 'Reload the current notice.', status=409)
        column = 'read_at' if action == 'read' else 'cleared_at'
        updated = await tx.fetchrow(f'UPDATE l07_notices SET {column}=COALESCE({column},now()),revision=revision+1 WHERE id=$1 RETURNING *', notice_id)
        result = project(updated)
        # Store the canonical result with the mutation, not an optimistic browser marker.
        encoded = json.dumps(result, default=lambda value: value.isoformat())
        await tx.execute('INSERT INTO l07_notice_operations VALUES($1,$2,$3,$4::jsonb)', owner, key, fingerprint, encoded)
        await enqueue(tx, EventEnvelope(type='communications.inbox-changed.v1', source='communications', subject=str(owner), request_id=request.state.request_id,
            data={'recipient_id': str(owner), 'notice_id': str(notice_id), 'revision': result['revision']}), ['personal-invalidation'])
        return result


@router.post('/{notice_id}/read')
async def mark_read(notice_id: UUID, body: NoticeMutation, request: Request, owner=Depends(actor), key=Depends(idempotency)):
    return await mutate(notice_id, 'read', body, request, owner, key)


@router.post('/{notice_id}/clear')
async def clear(notice_id: UUID, body: NoticeMutation, request: Request, owner=Depends(actor), key=Depends(idempotency)):
    return await mutate(notice_id, 'clear', body, request, owner, key)


@router.get('/{notice_id}/destination')
async def destination(notice_id: UUID, request: Request, owner=Depends(actor)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM l07_notices WHERE id=$1 AND recipient_id=$2', notice_id, owner)
    if row is None:
        raise PublicError('not_found', 'Notice not found.', status=404)
    if row['resource_owner_id'] != owner:
        raise PublicError('destination_unavailable', 'This destination is not available.', status=403)
    resource = str(row['resource_id'])
    dependency, path, url = {
        'quote_ready': ('pricing', '/v1/quotes/' + resource, '/prices?quote_id=' + resource),
        'outbid': ('auction', '/v1/auctions/' + resource, '/watches/' + resource),
        'bid_accepted': ('auction', '/v1/auctions/' + resource, '/watches/' + resource),
        'reservation_ready': ('orders', '/v1/orders/' + resource, '/buying?reservation_id=' + resource),
        'payment_required': ('orders', '/v1/orders/' + resource, '/buying?reservation_id=' + resource),
        'case_update': ('trust', '/v1/cases/' + resource, '/buyer')
    }[row['kind']]
    review_notice = row['source'] == 'identity' and row['kind'] == 'case_update'
    if review_notice:
        dependency, path = 'identity', '/v1/private-reviews/' + resource
    response = await getattr(request.app.state, dependency).request('GET', path, headers={'Authorization': request.headers['Authorization'], 'X-Request-ID': request.state.request_id})
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise PublicError('destination_unavailable', 'This destination is not currently available.', status=503)
    # Resolve the auction's listing through its canonical projection, not an invented auction/listing ID equivalence.
    if row['kind'] in ('outbid', 'bid_accepted'):
        try:
            listing_id = UUID(response.json()['listing_id'])
        except (ValueError, TypeError, KeyError):
            raise PublicError('destination_unavailable', 'This destination is not currently available.', status=503) from None
        url = '/watches/' + str(listing_id)
    if review_notice:
        try:
            url = '/seller/verification' if UUID(response.json()['applicant_id']) == owner else '/operations/verification'
        except (ValueError, TypeError, KeyError):
            raise PublicError('destination_unavailable', 'This destination is not currently available.', status=503) from None
    # The owning service checks CURRENT access. A historical notice never grants access.
    return {'url': url, 'historical_revision': row['resource_revision']}
