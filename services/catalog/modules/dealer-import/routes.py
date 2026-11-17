"""Private atomic draft import; publication stays with listing commands."""
import hashlib
import json
from uuid import uuid4
from fastapi import APIRouter, Query, Request
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from modules.listings.dependencies import principal, seller_scope, upstream
from modules.listings.repository import emit
from bt_contracts.catalog.listings.v1 import WatchFacts
from .table import parse

router = APIRouter()


async def authority(request):
    person = await principal(request)
    seller_scope(person)
    organization = person.actor.organization_id
    if not organization:
        raise PublicError('dealer_required', 'Select an authorized dealer. اختر وكيلاً مخولاً.', status=403)
    business = await upstream(request, 'identity', 'GET', f'/v1/businesses/{organization}')
    if not isinstance(business, dict) or business.get('id') != str(organization):
        raise PublicError('unavailable', 'Retry the same reference. أعد المحاولة بالمرجع نفسه.', status=503)
    if not (business.get('kind') == 'dealer' and business.get('state') == 'active'
            and business.get('platform_onboarded') is True and business.get('authenticated_business') is True
            and 'sales' in business.get('capabilities', []) and business.get('public_name')):
        raise PublicError('dealer_required', 'Current dealer access is required. يلزم وصول حالي للوكيل.', status=403)
    return person, business


async def current_scope(request, original):
    person, business = await authority(request)
    if (person.actor.subject_id != original.actor.subject_id
            or person.actor.organization_id != original.actor.organization_id):
        raise PublicError('denied', 'Access denied. الوصول مرفوض.', status=403)
    return person, business


def page(value, offset, limit):
    return {**value, 'items': value['items'][offset:offset + limit], 'offset': offset, 'limit': limit}


def owned(row, person):
    if row is None or row['actor_id'] != person.actor.subject_id or row['organization_id'] != person.actor.organization_id:
        raise PublicError('denied', 'Access denied. الوصول مرفوض.', status=403)


@router.get('/v1/seller/imports/{operation_id}')
async def lookup(operation_id: str, request: Request, offset: int = Query(0, ge=0, le=1000), limit: int = Query(50, ge=1, le=50)):
    person, _ = await authority(request)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM catalog_dealer_imports WHERE operation_id=$1', operation_id)
    owned(row, person)
    return page(json.loads(row['result']), offset, limit)


@router.post('/v1/seller/imports')
async def create(request: Request):
    person, business = await authority(request)
    operation = request.headers.get('Idempotency-Key', '')
    if not 1 <= len(operation) <= 128:
        raise PublicError('invalid_operation', 'A stable reference is required. يلزم مرجع ثابت.', status=422)
    if request.headers.get('If-Match') != '0':
        raise PublicError('stale_revision', 'Reload the current revision. أعد تحميل الإصدار الحالي.', status=409)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 1_000_000:
            raise PublicError('table_limit', 'File exceeds the limit. يتجاوز الملف الحد.', status=413)
    try:
        rows = parse(bytes(content))
    except ValueError:
        raise PublicError('invalid_table', 'Check the table format and limits. تحقق من صيغة الجدول وحدوده.', status=422) from None
    digest = hashlib.sha256(content).hexdigest()
    async with unit_of_work(request.app.state.pool, lock_key='dealer-import:' + operation) as tx:
        person, business = await current_scope(request, person)
        previous = await tx.fetchrow('SELECT * FROM catalog_dealer_imports WHERE operation_id=$1', operation)
        if previous:
            owned(previous, person)
            if previous['digest'] != digest:
                raise PublicError('operation_conflict', 'Retry identical content. أعد إرسال المحتوى نفسه.', status=409)
            return page(json.loads(previous['result']), 0, 50)
        for serial in sorted({r['serial_digest'] for r in rows if r['state'] == 'valid'}):
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', serial)
        person, business = await current_scope(request, person)
        outcomes = []
        for row in rows:
            outcome = {'row': row['row'], 'state': 'invalid', 'listing_id': None}
            if row['state'] == 'valid':
                listing_id = uuid4()
                # Serialize serial admission independently of operation references.
                duplicate = await tx.fetchval('SELECT listing_id FROM catalog_dealer_import_serials WHERE serial_digest=$1', row['serial_digest'])
                if duplicate:
                    outcome['state'] = 'duplicate'
                else:
                    saved = await tx.fetchrow('''INSERT INTO catalog_listings
                        (id,owner_subject_id,organization_id,seller_type,seller_label,physical_watch_id,facts)
                        VALUES($1,$2,$3,'dealer',$4,$5,$6::jsonb) RETURNING *''', listing_id,
                        person.actor.subject_id, person.actor.organization_id, business['public_name'][:160],
                        uuid4(), WatchFacts.model_validate(row['facts']).model_dump_json())
                    await tx.execute('INSERT INTO catalog_dealer_import_serials VALUES($1,$2)', row['serial_digest'], listing_id)
                    await emit(tx, request, saved, 'draft-saved')
                    outcome.update(state='draft', listing_id=str(listing_id))
            outcomes.append(outcome)
        await current_scope(request, person)
        result = dict(schema_version='dealer-import.v1', operation_id=operation,
                      subject_id=None, watch_id=None, actor_id=str(person.actor.subject_id),
                      organization_id=str(person.actor.organization_id), expected_revision=0,
                      state='succeeded', revision=1, pending_reason=None, next_actor=None,
                      next_review_at=None, total=len(outcomes), items=outcomes)
        await tx.execute('INSERT INTO catalog_dealer_imports(operation_id,actor_id,organization_id,digest,result) VALUES($1,$2,$3,$4,$5::jsonb)',
                         operation, person.actor.subject_id, person.actor.organization_id, digest, json.dumps(result))
        return page(result, 0, 50)
