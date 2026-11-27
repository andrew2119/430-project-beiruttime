"""Retained closed-winner economics. New auction purchases are refused."""
import json
from uuid import UUID, NAMESPACE_URL, uuid5
from fastapi import APIRouter, Depends, Request
from pydantic import Field, StrictInt, ValidationError
from bt_contracts.pricing.quotes.auction import AuctionWinnerSource, AuctionWinnerReceipt, AuctionQuoteContext
from bt_contracts_core.models import Actor, Contract
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import CurrentPrincipal
from service_app import peers
from service_app.current import POLICY, buyer, decoded, digest, percentage, remember, replay
from service_app.security import idempotency

router = APIRouter()


class AuctionPreview(Contract):
    auction_id: UUID
    expected_revision: StrictInt = Field(ge=1)


class WinnerQuote(AuctionPreview):
    buyer_id: UUID
    operation_key: str = Field(min_length=8, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')


class AuctionReview(Contract):
    quote_revision: StrictInt = Field(ge=1)
    payable_minor: StrictInt = Field(gt=0, le=18_000_000_000_000)


async def source(request, auction_id, kind, buyer_id):
    context = await peers.call(request, 'auction', 'GET',
        f'/internal/v2/auctions/{auction_id}/quote-context?kind={kind}&buyer_id={buyer_id}', internal=True)
    try:
        context = AuctionQuoteContext.model_validate(context)
    except ValidationError:
        raise PublicError('dependency_unavailable', 'The exact auction source cannot be verified.', status=503) from None
    if (context.auction_id != auction_id or context.buyer_id != buyer_id
            or context.mode != ('closed_winner' if kind == 'winner' else 'bidding')
            or (kind == 'winner' and context.close_version < 1)):
        raise PublicError('source_changed', 'The exact auction scope changed.', status=409)
    return context.model_dump(mode='json')


async def create(request, p, key, body, kind, *, fingerprint=None):
    if kind != 'winner':
        raise PublicError('auction_purchase_disabled', 'Buy Now is available only for fixed-price listings.', status=409)
    fingerprint = fingerprint or digest([kind, body.model_dump(mode='json')])
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
    if prior:
        return prior
    context = await source(request, body.auction_id, kind, p.actor.subject_id)
    try:
        if (context['auction_id'] != str(body.auction_id) or context['buyer_id'] != str(p.actor.subject_id)
                or context['revision'] != body.expected_revision):
            raise PublicError('source_changed', 'Review the current auction.', status=409)
        if context['seller_id'] == str(p.actor.subject_id) or (context['seller_organization_id'] and
                UUID(context['seller_organization_id']) in p.organizations):
            raise AccessDenied('Self purchase is not permitted')
        price = context['price_minor']
        if type(price) is not int or not 0 < price <= 9_000_000_000_000 or context['currency'] != 'USD':
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise PublicError('dependency_unavailable', 'The exact auction source cannot be verified.', status=503) from None
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        if prior:
            return prior
        now = await tx.fetchval('SELECT clock_timestamp()')
        quote_id = uuid5(NAMESPACE_URL, f'pricing-auction:{p.actor.subject_id}:{key}')
        fee, commission = percentage(price, POLICY['buyer_fee_bps']), percentage(price, POLICY['seller_commission_bps'])
        expires = None
        snapshot = {**context, 'id': str(quote_id), 'owner_id': str(p.actor.subject_id), 'kind': kind,
            'subject_id': str(body.auction_id), 'subject_revision': body.expected_revision,
            'revision': 1, 'purpose': 'purchase', 'source': 'auction', 'source_verified': True,
            'price_minor': price, 'buyer_fee_minor': fee, 'seller_commission_minor': commission,
            'seller_net_minor': price - commission, 'shipping_minor': 0, 'tax_minor': 0,
            'payable_minor': price + fee, 'policy': POLICY, 'sample': True, 'schedule_id': POLICY['schedule_id'],
            'rounding': POLICY['rounding'], 'minor_unit_exponent': 2,
            'created_at': now.isoformat(), 'expires_at': None, 'reviewed_at': None}
        await tx.execute('''INSERT INTO l14_auction_quotes(id,auction_id,buyer_id,kind,snapshot,expires_at)
            VALUES($1,$2,$3,$4,$5::jsonb,$6)''', quote_id, body.auction_id, p.actor.subject_id, kind, json.dumps(snapshot), expires)
        return await remember(tx, p, key, fingerprint, {'status': 'succeeded', 'quote': snapshot})


@router.post('/v1/auction-quotes', status_code=201)
@router.post('/v2/auction-quotes', status_code=201)
async def preview(body: AuctionPreview, request: Request, p=Depends(peers.principal), key=Depends(idempotency)):
    buyer(p)
    return await create(request, p, key, body, 'prebid')


@router.post('/internal/v2/auction-quotes', status_code=201)
async def winner(body: WinnerQuote, request: Request):
    peers.service(request, {'auction'})
    if request.headers.get('idempotency-key') != body.operation_key:
        raise PublicError('idempotency_required', 'Use the original winner operation key.', status=422)
    p = CurrentPrincipal(actor=Actor(subject_id=body.buyer_id, session_id='service:auction'), roles=['buyer'])
    return await create(request, p, body.operation_key, body, 'winner')


@router.post('/internal/v2/auction-winner-quotes', status_code=201, response_model=AuctionWinnerReceipt)
async def winner_source(body: AuctionWinnerSource, request: Request):
    """L13's close-command shape, re-proven against the canonical Auction row."""
    peers.service(request, {'auction'})
    key = request.headers.get('idempotency-key')
    if key != 'close:' + str(body.auction_id):
        raise PublicError('idempotency_required', 'Use the original close operation key.', status=422)
    p = CurrentPrincipal(actor=Actor(subject_id=body.buyer_id, session_id='service:auction'), roles=['buyer'])
    fingerprint = digest(['winner-source', body.model_dump(mode='json')])
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
    if prior:
        result = prior
    else:
        context = await source(request, body.auction_id, 'winner', body.buyer_id)
        bindings = {'auction_id': str(body.auction_id), 'buyer_id': str(body.buyer_id),
            'watch_id': str(body.watch_id), 'listing_id': str(body.listing_id),
            'seller_id': str(body.seller_id),
            'seller_organization_id': str(body.organization_id) if body.organization_id else None,
            'currency': body.currency, 'price_minor': body.price_minor,
            'end_version': body.end_version, 'close_version': body.close_version, 'mode': 'closed_winner'}
        if (body.source_id != body.auction_id or any(context.get(k) != v for k, v in bindings.items())
                or any(type(context.get(k)) is not int for k in ('revision', 'price_minor', 'end_version', 'close_version'))):
            raise PublicError('source_changed', 'The exact closed winner changed.', status=409)
        command = WinnerQuote(auction_id=body.auction_id, buyer_id=body.buyer_id,
            expected_revision=context['revision'], operation_key=key)
        result = await create(request, p, key, command, 'winner', fingerprint=fingerprint)
    q = result['quote']
    return {'quote_id': q['id'], 'quote_revision': q['revision'], 'buyer_id': q['buyer_id'],
        'listing_id': q['listing_id'], 'source_id': q['auction_id'], 'currency': q['currency'],
        'price_minor': q['price_minor'], 'total_minor': q['payable_minor']}


@router.get('/v1/auction-quotes/{quote_id}')
@router.get('/v2/auction-quotes/{quote_id}')
async def read(quote_id: UUID, request: Request, p=Depends(peers.principal)):
    buyer(p)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM l14_auction_quotes WHERE id=$1 AND buyer_id=$2', quote_id, p.actor.subject_id)
    if not row:
        raise PublicError('not_found', 'Quote not found.', status=404)
    return {**decoded(row['snapshot']), 'reviewed_at': row['reviewed_at'].isoformat() if row['reviewed_at'] else None}


@router.post('/v1/auction-quotes/{quote_id}/review')
@router.post('/v2/auction-quotes/{quote_id}/review')
async def review(quote_id: UUID, body: AuctionReview, request: Request, p=Depends(peers.principal), key=Depends(idempotency)):
    buyer(p)
    fingerprint = digest(['auction-review', str(quote_id), body.model_dump(mode='json')])
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        if prior:
            return prior
        row = await tx.fetchrow('SELECT * FROM l14_auction_quotes WHERE id=$1 AND buyer_id=$2 FOR UPDATE', quote_id, p.actor.subject_id)
        if not row:
            raise PublicError('not_found', 'Quote not found.', status=404)
        q = decoded(row['snapshot'])
        now = await tx.fetchval('SELECT clock_timestamp()')
        if (row['expires_at'] is not None and now >= row['expires_at']) or body.quote_revision != row['revision'] or body.payable_minor != q['payable_minor']:
            raise PublicError('quote_binding_mismatch', 'Review the exact current auction quote.', status=409)
        await tx.execute('UPDATE l14_auction_quotes SET reviewed_at=coalesce(reviewed_at,$2) WHERE id=$1', quote_id, now)
        return await remember(tx, p, key, fingerprint, {'status': 'succeeded', 'quote': {**q, 'reviewed_at': (row['reviewed_at'] or now).isoformat()}})
