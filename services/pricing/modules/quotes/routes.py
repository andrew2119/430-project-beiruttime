import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Request
from bt_contracts.pricing.quotes.models import QuoteRequest, QuoteReview
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.security import actor, idempotency
from .calculation import calculate
from .catalog import current_listing

router = APIRouter(prefix='/v1/quotes', tags=['quotes'])
validation_router = APIRouter(prefix='/internal/v1/quotes', tags=['quote-validation'])

def digest(body):
    # Preserve V1 sample-command keys across the additive source-binding field.
    exclude = {'source'} if getattr(body, 'source', None) == 'sample' else set()
    return hashlib.sha256(body.model_dump_json(exclude=exclude).encode()).hexdigest()

def project(row):
    snapshot = json.loads(row['snapshot']) if isinstance(row['snapshot'], str) else row['snapshot']
    return {'source': 'sample', 'source_verified': False, **snapshot, 'reviewed_at': row['reviewed_at'].isoformat() if row['reviewed_at'] else None}

async def owned(tx, quote_id, owner):
    row = await tx.fetchrow('SELECT * FROM l07_quotes WHERE id=$1 AND owner_id=$2', quote_id, owner)
    if row is None:
        raise PublicError('not_found', 'Quote not found.', status=404)
    return row

@router.post('', status_code=201)
async def create(body: QuoteRequest, request: Request, owner=Depends(actor), key=Depends(idempotency)):
    # Recover a known acknowledgement before requiring a fresh dependency. A missing
    # outcome is rechecked under the write lock after the bounded publication read.
    async with request.app.state.pool.acquire() as tx:
        prior = await tx.fetchrow('SELECT * FROM l07_quotes WHERE owner_id=$1 AND idempotency_key=$2', owner, key)
    if prior:
        if prior['request_hash'] != digest(body):
            raise PublicError('idempotency_conflict', 'This request key belongs to different fields.', status=409)
        return project(prior)
    if body.source == 'listing':
        await current_listing(request, body.subject_id, body.subject_revision, body.price_minor, body.currency)
    async with unit_of_work(request.app.state.pool, lock_key=f'quote:{owner}:{key}') as tx:
        prior = await tx.fetchrow('SELECT * FROM l07_quotes WHERE owner_id=$1 AND idempotency_key=$2', owner, key)
        if prior:
            if prior['request_hash'] != digest(body):
                raise PublicError('idempotency_conflict', 'This request key belongs to different fields.', status=409)
            return project(prior)
        snapshot = calculate(body, owner, source_verified=body.source == 'listing')
        quote_id, now = UUID(snapshot['id']), datetime.fromisoformat(snapshot['created_at'])
        await tx.execute('INSERT INTO l07_quotes(id,owner_id,idempotency_key,request_hash,snapshot,created_at,expires_at) VALUES($1,$2,$3,$4,$5::jsonb,$6,$7)',
            quote_id, owner, key, digest(body), json.dumps(snapshot), now, datetime.fromisoformat(snapshot['expires_at']))
        event = EventEnvelope(type='pricing.quote-created.v1', source='pricing', subject=str(quote_id), request_id=request.state.request_id,
            data={'occurrence_id': 'quote:' + str(quote_id), 'recipient_id': str(owner), 'kind': 'quote_ready', 'resource_id': str(quote_id),
                  'resource_revision': 1, 'resource_owner_id': str(owner), 'event_time': now.isoformat(), 'sample': True, 'required': False})
        await enqueue(tx, event, ['communications'])
        return snapshot

@router.get('')
async def list_quotes(request: Request, owner=Depends(actor)):
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch('SELECT * FROM l07_quotes WHERE owner_id=$1 ORDER BY created_at DESC,id DESC LIMIT 30', owner)
        return {'items': [project(row) for row in rows]}

@router.get('/{quote_id}')
async def read(quote_id: UUID, request: Request, owner=Depends(actor)):
    async with request.app.state.pool.acquire() as tx:
        return project(await owned(tx, quote_id, owner))

@router.post('/{quote_id}/review')
async def review(quote_id: UUID, body: QuoteReview, request: Request, owner=Depends(actor), key=Depends(idempotency)):
    async with request.app.state.pool.acquire() as tx:
        before = await owned(tx, quote_id, owner)
    basis = project(before)
    if before['reviewed_at'] is None:
        if datetime.now(timezone.utc) >= before['expires_at']:
            raise PublicError('quote_expired', 'Review a new quote before continuing.', status=409,
                details={'next_action': 'review_current_quote'})
        if basis.get('source_verified') and basis.get('source') == 'listing':
            await current_listing(request, UUID(basis['subject_id']), basis['subject_revision'], basis['price_minor'], basis['currency'])
    async with unit_of_work(request.app.state.pool, lock_key='quote-review:' + str(owner)) as tx:
        row = await owned(tx, quote_id, owner)
        snapshot = project(row)
        for name in QuoteRequest.model_fields:
            if snapshot[name] != body.model_dump(mode='json')[name]:
                raise PublicError('quote_binding_mismatch', 'Review the current quote; bindings differ.', status=409, details={'next_action': 'review_current_quote'})
        if body.quote_revision != snapshot['revision'] or body.payable_minor != snapshot['payable_minor']:
            raise PublicError('quote_binding_mismatch', 'Review the current quote; amount or revision differs.', status=409)
        prior = await tx.fetchrow('SELECT * FROM l07_quote_reviews WHERE quote_id=$1', quote_id)
        if prior:
            if prior['idempotency_key'] != key or prior['request_hash'] != digest(body):
                raise PublicError('already_reviewed', 'This version was already reviewed.', status=409)
            return snapshot
        used_key = await tx.fetchval('SELECT quote_id FROM l07_quote_reviews WHERE owner_id=$1 AND idempotency_key=$2', owner, key)
        if used_key is not None:
            raise PublicError('idempotency_conflict', 'This request key belongs to another quote review.', status=409)
        now = datetime.now(timezone.utc)
        if now >= row['expires_at']:
            raise PublicError('quote_expired', 'Review a new quote before continuing.', status=409, details={'next_action': 'review_current_quote'})
        await tx.execute('INSERT INTO l07_quote_reviews VALUES($1,$2,$3,$4,$5)', quote_id, owner, key, digest(body), now)
        await tx.execute('UPDATE l07_quotes SET reviewed_at=$2 WHERE id=$1', quote_id, now)
        await enqueue(tx, EventEnvelope(type='pricing.quote-reviewed.v1', source='pricing', subject=str(quote_id), request_id=request.state.request_id,
            data={'quote_id': str(quote_id), 'owner_id': str(owner), 'revision': 1}), ['communications'])
        return {**snapshot, 'reviewed_at': now.isoformat()}


@validation_router.get('/{quote_id}/validation')
async def validate_for_reservation(quote_id: UUID, request: Request, owner=Depends(actor)):
    async with request.app.state.pool.acquire() as tx:
        row = await owned(tx, quote_id, owner)
        quote = project(row)
    if quote['purpose'] != 'purchase' or quote.get('source') != 'listing' or not quote.get('source_verified'):
        raise PublicError('quote_not_authoritative', 'Request a quote bound to the current listing before reserving.', status=403,
            details={'next_action': 'review_current_listing'})
    if datetime.now(timezone.utc) >= row['expires_at']:
        raise PublicError('quote_expired', 'Review a new quote before continuing.', status=409,
            details={'next_action': 'review_current_quote'})
    await current_listing(request, UUID(quote['subject_id']), quote['subject_revision'], quote['price_minor'], quote['currency'])
    if datetime.now(timezone.utc) >= row['expires_at']:
        raise PublicError('quote_expired', 'Review a new quote before continuing.', status=409,
            details={'next_action': 'review_current_quote'})
    # Exact L08 ValidatedQuote v1; this authorizes no charge, custody or payout.
    return {'quote_id': str(quote_id), 'buyer_id': str(owner), 'listing_id': quote['subject_id'],
        'listing_revision': quote['subject_revision'], 'currency': quote['currency'],
        'total_minor': quote['payable_minor'], 'expires_at': quote['expires_at'], 'status': 'valid'}
