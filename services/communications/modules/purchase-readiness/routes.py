import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from bt_bulkheads import Unavailable
from bt_contracts.pricing.quotes.models import OfferDraftRequest, OfferDraftUpdate, QuoteSnapshot
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.security import actor, idempotency

router = APIRouter(prefix='/v1/buying', tags=['purchase-readiness'])
RELEASE = {'payment': False, 'send_offer': False, 'accept_offer': False}
ROUTES = [{'id': key, 'label': label, 'released': False} for key, label in (
    ('card', {'en': 'Simulated card', 'ar': 'بطاقة محاكاة'}), ('whish', {'en': 'Whish', 'ar': 'ويش'}), ('omt', {'en': 'OMT', 'ar': 'أو إم تي'}))]

def project(row):
    return {key: str(value) if isinstance(value, UUID) else value.isoformat() if hasattr(value, 'isoformat') else value
        for key, value in dict(row).items() if key != 'owner_id'} | {'status': 'draft'}

@router.get('/drafts')
async def listing(request: Request, owner=Depends(actor)):
    async with request.app.state.pool.acquire() as tx:
        return {'items': [project(row) for row in await tx.fetch('SELECT * FROM l07_offer_drafts WHERE owner_id=$1 ORDER BY updated_at DESC,id DESC LIMIT 50', owner)]}

async def save(body, request, owner, key, draft_id=None):
    fingerprint = hashlib.sha256((str(draft_id) + body.model_dump_json()).encode()).hexdigest()
    async with unit_of_work(request.app.state.pool, lock_key='offer-draft:' + str(owner)) as tx:
        prior = await tx.fetchrow('SELECT * FROM l07_offer_operations WHERE owner_id=$1 AND idempotency_key=$2', owner, key)
        if prior:
            if prior['request_hash'] != fingerprint:
                raise PublicError('idempotency_conflict', 'Request key fields differ.', status=409)
            return json.loads(prior['result'])
        if draft_id is None:
            draft_id = uuid4()
            row = await tx.fetchrow('''INSERT INTO l07_offer_drafts(id,owner_id,subject_id,subject_revision,currency,amount_minor)
                VALUES($1,$2,$3,$4,$5,$6) RETURNING *''', draft_id, owner, body.subject_id, body.subject_revision, body.currency, body.amount_minor)
        else:
            existing = await tx.fetchrow('SELECT * FROM l07_offer_drafts WHERE id=$1 AND owner_id=$2 FOR UPDATE', draft_id, owner)
            if not existing:
                raise PublicError('not_found', 'Draft not found.', status=404)
            if existing['revision'] != body.expected_revision:
                raise PublicError('stale_revision', 'Reload the saved draft.', status=409)
            row = await tx.fetchrow('''UPDATE l07_offer_drafts SET subject_id=$3,subject_revision=$4,currency=$5,amount_minor=$6,
                revision=revision+1,updated_at=now() WHERE id=$1 AND owner_id=$2 RETURNING *''',
                draft_id, owner, body.subject_id, body.subject_revision, body.currency, body.amount_minor)
        result = project(row)
        await tx.execute('INSERT INTO l07_offer_operations VALUES($1,$2,$3,$4::jsonb)', owner, key, fingerprint, json.dumps(result))
        await enqueue(tx, EventEnvelope(type='communications.offer-draft-saved.v1', source='communications', subject=str(draft_id), request_id=request.state.request_id,
            data={'owner_id': str(owner), 'draft_id': str(draft_id), 'revision': row['revision']}), ['personal-invalidation'])
        return result

@router.post('/drafts', status_code=201)
async def create(body: OfferDraftRequest, request: Request, owner=Depends(actor), key=Depends(idempotency)):
    return await save(body, request, owner, key)

@router.get('/drafts/{draft_id}')
async def read(draft_id: UUID, request: Request, owner=Depends(actor)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM l07_offer_drafts WHERE id=$1 AND owner_id=$2', draft_id, owner)
        if row is None:
            raise PublicError('not_found', 'Draft not found.', status=404)
        return project(row)

@router.put('/drafts/{draft_id}')
async def update(draft_id: UUID, body: OfferDraftUpdate, request: Request, owner=Depends(actor), key=Depends(idempotency)):
    return await save(body, request, owner, key, draft_id)

@router.get('/readiness')
async def readiness(request: Request, owner=Depends(actor), reservation_id: UUID | None = None, quote_id: UUID | None = None):
    headers = {'Authorization': request.headers['Authorization'], 'X-Request-ID': request.state.request_id}
    reservation, quote = {'status': 'not_selected'}, {'status': 'not_selected'}
    bound_quote_id = None
    if reservation_id:
        response = await request.app.state.orders.request('GET', '/v1/orders/' + str(reservation_id), headers=headers)
        if isinstance(response, Unavailable):
            reservation = {'status': 'unavailable'}
        elif response.status_code != 200:
            reservation = {'status': 'unavailable' if response.status_code >= 500 else 'denied'}
        else:
            try:
                payload = response.json()
                record = payload['order']
                if UUID(record['id']) != reservation_id or record['state'] not in ('awaiting_payment', 'payment_unknown', 'expired_fenced'):
                    raise ValueError('Invalid reservation projection')
                if record['currency'] not in ('USD', 'LBP') or type(record['total_minor']) is not int or not 0 <= record['total_minor'] <= 9_000_000_000_000_000:
                    raise ValueError('Invalid reservation money')
                if not isinstance(record['deadline'], str) or type(record['revision']) is not int or record['revision'] < 1:
                    raise ValueError('Invalid reservation revision or deadline')
                if record['payment_authority'] is not False or datetime.fromisoformat(record['deadline'].replace('Z', '+00:00')).tzinfo is None:
                    raise ValueError('Invalid reservation release metadata')
                if UUID(record['buyer_id']) != owner:
                    reservation = {'status': 'denied'}
                else:
                    if record.get('quote_id') is not None:
                        bound_quote_id = UUID(record['quote_id'])
                    if record.get('listing_id') is not None:
                        UUID(record['listing_id'])
                    if record.get('is_demo') is not None and type(record['is_demo']) is not bool:
                        raise ValueError('Invalid sample content metadata')
                    # Never serialize history, custody evidence or another party's identifiers.
                    reservation = {'status': 'available', 'record': {k: record[k] for k in ('id','state','quote_id','listing_id','is_demo','currency','total_minor','deadline','revision') if k in record}}
            except (ValueError, TypeError, KeyError):
                reservation = {'status': 'unavailable'}
    if reservation['status'] == 'available':
        if bound_quote_id is None:
            quote, quote_id = {'status': 'binding_unavailable'}, None
        elif quote_id is not None and quote_id != bound_quote_id:
            raise PublicError('quote_binding_mismatch', 'Use the exact quote retained by this reservation.', status=409,
                details={'next_action': 'review_current_reservation'})
        else:
            quote_id = bound_quote_id
    if quote_id:
        response = await request.app.state.pricing.request('GET', '/v1/quotes/' + str(quote_id), headers=headers)
        if isinstance(response, Unavailable):
            quote = {'status': 'unavailable'}
        elif response.status_code == 200:
            try:
                record = QuoteSnapshot.model_validate(response.json())
                if record.id != quote_id or record.owner_id != owner:
                    raise ValueError('Invalid quote projection')
                if reservation['status'] == 'available' and (record.currency != reservation['record']['currency']
                    or record.payable_minor != reservation['record']['total_minor'] or record.purpose != 'purchase' or not record.source_verified
                    or datetime.fromisoformat(reservation['record']['deadline'].replace('Z', '+00:00')) > record.expires_at
                    or (reservation['record'].get('listing_id') is not None and UUID(reservation['record']['listing_id']) != record.subject_id)):
                    raise ValueError('Reservation fee binding differs')
                quote = {'status': 'available', 'record': record.model_dump(mode='json')}
            except (ValueError, TypeError, KeyError):
                quote = {'status': 'unavailable'}
        else:
            quote = {'status': 'denied'}
    return {'release': RELEASE, 'routes': ROUTES, 'reservation': reservation, 'quote': quote,
            'drafts': (await listing(request, owner))['items']}

async def unreleased():
    raise PublicError('capability_not_released', 'This action is not released. Save a draft or review readiness instead.', status=403,
        details={'next_action': 'review_readiness', 'release': RELEASE})

@router.post('/payment')
async def payment(request: Request, owner=Depends(actor)):
    await unreleased()

@router.post('/drafts/{draft_id}/send')
async def send(draft_id: UUID, request: Request, owner=Depends(actor)):
    await read(draft_id, request, owner)
    await unreleased()

@router.post('/drafts/{draft_id}/accept')
async def accept(draft_id: UUID, request: Request, owner=Depends(actor)):
    await read(draft_id, request, owner)
    await unreleased()
