"""Price validity, current scope and retained history have separate authority."""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Request
from bt_contracts.pricing.offers.current import is_current, require_current
from bt_contracts.pricing.quotes.current import CurrentQuoteV3, FixedPurchaseCommitV3
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from service_app import peers
from service_app.assessed import current_source
from service_app.current import decoded, require_usd

router = APIRouter()


@router.get('/v1/pricing-operations/{key}')
async def operation(key: str, request: Request, p=Depends(peers.principal)):
    if not 8 <= len(key) <= 128:
        raise PublicError('invalid_key', 'Use the original operation key.', status=422)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM l14_pricing_operations WHERE actor_id=$1 AND operation_key=$2', p.actor.subject_id, key)
        if row is None or row['organization_id'] != p.actor.organization_id:
            raise PublicError('not_found', 'Operation not found in this scope.', status=404)
        result = decoded(row['result'])
        receipt = result.get('offer')
        if isinstance(receipt, dict) and not is_current(receipt.get('quote')):
            offer = await tx.fetchrow('SELECT state,orders_command FROM l14_offers WHERE id=$1', UUID(receipt['id']))
            require_current(receipt.get('quote'), state=offer['state'] if offer else receipt.get('state'),
                            has_intent=offer is not None and offer['orders_command'] is not None)
    return result


Commitment = FixedPurchaseCommitV3


@router.post('/internal/v3/quotes/{quote_id}/commit')
async def commit(quote_id: UUID, body: Commitment, request: Request):
    """Orders attests its durable allocation time, never a browser-supplied promise."""
    peers.service(request, {'orders'})
    async with unit_of_work(request.app.state.pool, lock_key='quote-commit:' + str(quote_id)) as tx:
        row = await tx.fetchrow('SELECT * FROM l07_quotes WHERE id=$1 AND owner_id=$2', quote_id, body.buyer_id)
        if row is None:
            raise PublicError('not_found', 'Purchase quote not found.', status=404)
        q = decoded(row['snapshot'])
        require_usd(q)
        prior = await tx.fetchrow('SELECT * FROM l14_quote_commitments WHERE quote_id=$1', quote_id)
        if prior:
            if any(prior[key] != getattr(body, key) for key in Commitment.model_fields):
                raise PublicError('commitment_conflict', 'The retained commitment has different fields.', status=409)
            return {'status': 'committed', 'quote_id': str(quote_id), 'expires_at': None}
        if (not row['reviewed_at'] or not row['reviewed_at'] <= body.committed_at < row['expires_at']
                or body.committed_at > await tx.fetchval('SELECT clock_timestamp()')
                or q.get('source') != 'listing' or q.get('source_verified') is not True or q['purpose'] != 'purchase'
                or body.quote_revision != q['revision'] or body.total_minor != q['payable_minor']):
            raise PublicError('quote_binding_mismatch', 'Attest the exact reviewed purchase at its allocation time.', status=409)
        await tx.execute('''INSERT INTO l14_quote_commitments(quote_id,buyer_id,order_id,quote_revision,currency,total_minor,committed_at)
            VALUES($1,$2,$3,$4,'USD',$5,$6)''', quote_id, body.buyer_id, body.order_id, body.quote_revision, body.total_minor, body.committed_at)
        await enqueue(tx, EventEnvelope(type='pricing.economics-committed.v3', source='pricing', subject=str(quote_id),
            request_id=request.state.request_id, data={'quote_id': str(quote_id), 'buyer_id': str(body.buyer_id),
                'order_id': str(body.order_id), 'quote_revision': body.quote_revision, 'currency': 'USD',
                'total_minor': body.total_minor, 'committed_at': body.committed_at.isoformat()}), ['committed-quotes-v3'])
    return {'status': 'committed', 'quote_id': str(quote_id), 'expires_at': None}


@router.get('/internal/v3/quotes/{quote_id}/validation', response_model=CurrentQuoteV3)
async def validation(quote_id: UUID, buyer_id: UUID, request: Request):
    caller = peers.service(request, {'orders', 'catalog', 'eligibility', 'service-operations'})
    async with request.app.state.pool.acquire() as tx:
        auction = await tx.fetchrow('SELECT * FROM l14_auction_quotes WHERE id=$1', quote_id)
        offer = await tx.fetchrow('SELECT * FROM l14_offers WHERE quote_id=$1', quote_id)
        assessed = await tx.fetchrow('SELECT * FROM l14_assessed_quotes WHERE id=$1', quote_id)
        decision = await tx.fetchrow('SELECT * FROM l14_quote_decisions WHERE quote_id=$1', quote_id) if assessed else None
    now = datetime.now(timezone.utc)
    if auction:
        q = decoded(auction['snapshot'])
        if caller != 'orders' or buyer_id != auction['buyer_id']:
            raise AccessDenied('Wrong auction quote subject or consumer')
        if auction['kind'] != 'winner':
            raise PublicError('legacy_reconciliation', 'Legacy auction purchases require recorded reconciliation.', status=409)
        from .auction_routes import source
        context = await source(request, auction['auction_id'], 'winner', buyer_id)
        for key in ('close_version', 'end_version', 'price_minor', 'currency', 'listing_id', 'listing_revision', 'watch_id'):
            if context.get(key) != q.get(key):
                raise PublicError('source_changed', 'The retained auction winner scope changed.', status=409)
        result = {'source_id': auction['auction_id'], 'source_revision': q['subject_revision'], 'kind': 'winner',
                  'listing_id': q['listing_id'], 'listing_revision': q['listing_revision'], 'expires_at': None,
                  'accepted_at': auction['created_at'], 'total_minor': q['payable_minor'], 'economics': 'committed'}
    elif offer:
        q = decoded(offer['snapshot'])
        if buyer_id != offer['buyer_id'] or caller != 'orders':
            raise AccessDenied('Wrong quote subject or consumer')
        if offer['state'] not in ('acceptance_pending', 'accepted'):
            raise PublicError('quote_not_current', 'An admitted accepted offer intent is required.', status=409)
        # Sent offers hold an immutable copy of the original quote binding.
        require_current(q, state=offer['state'])
        await peers.listing(request, offer['listing_id'], offer['listing_revision'])
        result = {'source_id': offer['id'], 'source_revision': offer['accepted_revision'], 'kind': 'offer',
                  'listing_id': offer['listing_id'], 'listing_revision': offer['listing_revision'],
                  'total_minor': q['payable_minor'], 'expires_at': None, 'economics': 'committed',
                  'accepted_at': offer['accepted_at']}
    elif assessed:
        q = decoded(assessed['snapshot'])
        if buyer_id != assessed['buyer_id']:
            raise AccessDenied('Wrong quote subject')
        if assessed['state'] != 'accepted' or not decision or decision['decision'] != 'accepted':
            raise PublicError('quote_not_current', 'Explicit current customer acceptance is required.', status=409)
        source = await current_source(request, assessed['kind'], q)
        if source['buyer_id'] != str(buyer_id) or source['organization_id'] != str(assessed['organization_id']):
            raise PublicError('source_changed', 'Current assessed scope changed.', status=409)
        totals = decoded(decision['amounts'])
        result = {'source_id': assessed['source_id'], 'source_revision': assessed['source_revision'], 'kind': assessed['kind'],
                  'assessment_id': q['assessment_id'], 'assessment_revision': q['assessment_revision'],
                  'organization_id': assessed['organization_id'], 'total_minor': totals['payable_minor'],
                  'expires_at': None, 'accepted_at': decision['decided_at'], 'economics': 'committed',
                  'selected_line_ids': decoded(decision['selected_line_ids']), 'terms_digest': decision['terms_digest'],
                  'accepted_fee_lines': decoded(decision['accepted_fee_lines'])}
    else:
        async with request.app.state.pool.acquire() as tx:
            row = await tx.fetchrow('SELECT * FROM l07_quotes WHERE id=$1 AND owner_id=$2', quote_id, buyer_id)
            commitment = await tx.fetchrow('SELECT * FROM l14_quote_commitments WHERE quote_id=$1', quote_id)
        if not row:
            if caller == 'orders' and commitment and commitment['buyer_id'] == buyer_id:
                raise PublicError('legacy_reconciliation', 'Legacy purchase economics require recorded reconciliation.', status=409)
            raise PublicError('not_found', 'Current quote not found.', status=404)
        q = decoded(row['snapshot'])
        if (caller != 'orders' or not row['reviewed_at'] or q.get('source') != 'listing'
                or q.get('source_verified') is not True or q['purpose'] != 'purchase'
                or (not commitment and now >= row['expires_at'])):
            raise PublicError('quote_not_current', 'Review a current authoritative purchase quote.', status=409)
        if not commitment:
            from .catalog import current_listing
            await current_listing(request, UUID(q['subject_id']), q['subject_revision'], q['price_minor'], q['currency'])
        result = {'source_id': q['subject_id'], 'source_revision': q['subject_revision'], 'kind': 'purchase',
                  'listing_id': q['subject_id'], 'listing_revision': q['subject_revision'], 'total_minor': q['payable_minor'],
                  'expires_at': None if commitment else row['expires_at'], 'accepted_at': commitment['committed_at'] if commitment else row['reviewed_at'],
                  'economics': 'committed' if commitment else 'preview'}
    require_usd(q)
    policy = q['policy']
    if policy.get('revision') != 2:
        raise PublicError('legacy_reconciliation', 'Retain old terms for reconciliation; do not silently reprice them.', status=409)
    return {**result, 'quote_id': quote_id, 'quote_revision': q['revision'], 'buyer_id': buyer_id,
            'currency': q['currency'], 'schedule_id': q['schedule_id'], 'policy_revision': policy['revision'],
            'rounding': q['rounding'] if 'rounding' in q else policy['rounding'], 'status': 'valid',
            'execution_authority': 'not_granted'}


@router.get('/internal/v2/quotes/{quote_id}/validation')
async def legacy_validation(quote_id: UUID, buyer_id: UUID, request: Request):
    peers.service(request, {'orders', 'catalog', 'eligibility', 'service-operations'})
    raise PublicError('contract_upgrade_required', 'Use pricing-current/v3 for separate preview and committed economics.', status=409)
