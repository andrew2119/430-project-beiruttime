"""Current authority is separate from a retained, possibly expired review."""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Request
from bt_contracts.pricing.quotes.current import CurrentQuote
from bt_contracts_core.errors import AccessDenied, PublicError
from service_app import peers
from service_app.assessed import current_source
from service_app.current import decoded

router = APIRouter()


@router.get('/v1/pricing-operations/{key}')
async def operation(key: str, request: Request, p=Depends(peers.principal)):
    if not 8 <= len(key) <= 128:
        raise PublicError('invalid_key', 'Use the original operation key.', status=422)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM l14_pricing_operations WHERE actor_id=$1 AND operation_key=$2', p.actor.subject_id, key)
    if row is None or row['organization_id'] != p.actor.organization_id:
        raise PublicError('not_found', 'Operation not found in this scope.', status=404)
    return decoded(row['result'])


@router.get('/internal/v2/quotes/{quote_id}/validation', response_model=CurrentQuote)
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
        if now >= auction['expires_at'] or (auction['kind'] == 'prebid' and auction['reviewed_at'] is None):
            raise PublicError('quote_not_current', 'Review the exact current auction quote.', status=409)
        if auction['kind'] == 'prebid':
            # L12's immutable prepared intent binds admission revision R even
            # while freeze/reservation advances the public row to R+1/R+2.
            # Never guess the admission revision from a current row counter.
            context = await peers.call(request, 'auction', 'GET',
                f"/internal/v1/auctions/{auction['auction_id']}/prebid-basis?quote_id={quote_id}&buyer_id={buyer_id}", internal=True)
            valid = (context.get('auction_id') == str(auction['auction_id'])
                and context.get('buyer_id') == str(buyer_id) and context.get('quote_id') == str(quote_id)
                and context.get('quote_revision') == auction['revision']
                and context.get('admission_revision') == q['subject_revision']
                and context.get('mode') in ('prebid_pending', 'prebid_reserved')
                and context.get('total_minor') == q['payable_minor'])
        else:
            from .auction_routes import source
            context = await source(request, auction['auction_id'], auction['kind'], buyer_id)
            valid = context.get('revision') == q['subject_revision']
        numeric = ['price_minor', 'listing_revision'] + (['quote_revision', 'admission_revision', 'current_revision', 'total_minor'] if auction['kind'] == 'prebid' else ['revision'])
        if (not valid or any(type(context.get(field)) is not int for field in numeric)
                or context.get('price_minor') != q['price_minor']
                or context.get('currency') != q['currency'] or context.get('listing_id') != q['listing_id']
                or context.get('listing_revision') != q['listing_revision'] or context.get('watch_id') != q['watch_id']):
            raise PublicError('source_changed', 'The auction price or scope changed. Review a new quote.', status=409)
        result = {'quote_id': quote_id, 'quote_revision': auction['revision'], 'buyer_id': buyer_id,
            'source_id': auction['auction_id'], 'source_revision': q['subject_revision'], 'kind': auction['kind'],
            'listing_id': q['listing_id'], 'listing_revision': q['listing_revision'], 'currency': q['currency'],
            'total_minor': q['payable_minor'], 'expires_at': auction['expires_at'], 'accepted_at': auction['reviewed_at'],
            'schedule_id': q['schedule_id'], 'policy_revision': q['policy']['revision'], 'rounding': q['rounding'], 'status': 'valid'}
    elif offer:
        q = decoded(offer['snapshot'])
        if buyer_id != offer['buyer_id'] or caller != 'orders':
            raise AccessDenied('Wrong quote subject or consumer')
        if (offer['state'] not in ('acceptance_pending', 'accepted') or now >= offer['expires_at']
                or now >= datetime.fromisoformat(q['expires_at'])):
            raise PublicError('quote_not_current', 'A current accepted offer intent is required.', status=409)
        await peers.listing(request, offer['listing_id'], offer['listing_revision'])
        result = {'quote_id': quote_id, 'quote_revision': q['revision'], 'buyer_id': buyer_id,
            'source_id': offer['id'], 'source_revision': offer['revision'], 'kind': 'offer',
            'listing_id': offer['listing_id'], 'listing_revision': offer['listing_revision'],
            'currency': q['currency'], 'total_minor': q['payable_minor'], 'expires_at': min(offer['expires_at'], datetime.fromisoformat(q['expires_at'])),
            'schedule_id': q['schedule_id'], 'policy_revision': 1, 'rounding': q['rounding'], 'status': 'valid'}
    elif assessed:
        q = decoded(assessed['snapshot'])
        if buyer_id != assessed['buyer_id']:
            raise AccessDenied('Wrong quote subject')
        if assessed['state'] != 'accepted' or not decision or now >= assessed['expires_at']:
            raise PublicError('quote_not_current', 'Explicit current buyer acceptance is required.', status=409)
        source = await current_source(request, assessed['kind'], q)
        if source['buyer_id'] != str(buyer_id) or source['organization_id'] != str(assessed['organization_id']):
            raise PublicError('source_changed', 'Current assessed scope changed.', status=409)
        totals = decoded(decision['amounts'])
        result = {'quote_id': quote_id, 'quote_revision': assessed['revision'], 'buyer_id': buyer_id,
            'source_id': assessed['source_id'], 'source_revision': assessed['source_revision'], 'kind': assessed['kind'],
            'assessment_id': q['assessment_id'], 'assessment_revision': q['assessment_revision'],
            'organization_id': assessed['organization_id'], 'currency': q['currency'], 'total_minor': totals['payable_minor'],
            'expires_at': assessed['expires_at'], 'accepted_at': decision['decided_at'],
            'selected_line_ids': decoded(decision['selected_line_ids']), 'terms_digest': decision['terms_digest'],
            'schedule_id': q['schedule_id'], 'policy_revision': q['policy']['revision'], 'rounding': q['policy']['rounding'], 'status': 'valid'}
    else:
        async with request.app.state.pool.acquire() as tx:
            legacy = await tx.fetchrow('SELECT * FROM l07_quotes WHERE id=$1 AND owner_id=$2', quote_id, buyer_id)
        if not legacy:
            raise PublicError('not_found', 'Current quote not found.', status=404)
        q = decoded(legacy['snapshot'])
        if (caller != 'orders' or not legacy['reviewed_at'] or now >= legacy['expires_at']
                or q.get('source') != 'listing' or q.get('source_verified') is not True or q['purpose'] != 'purchase'):
            raise PublicError('quote_not_current', 'Review a current authoritative purchase quote.', status=409)
        from .catalog import current_listing
        await current_listing(request, UUID(q['subject_id']), q['subject_revision'], q['price_minor'], q['currency'])
        result = {'quote_id': quote_id, 'quote_revision': q['revision'], 'buyer_id': buyer_id,
            'source_id': q['subject_id'], 'source_revision': q['subject_revision'], 'kind': 'purchase',
            'listing_id': q['subject_id'], 'listing_revision': q['subject_revision'],
            'currency': q['currency'], 'total_minor': q['payable_minor'], 'expires_at': legacy['expires_at'],
            'accepted_at': legacy['reviewed_at'], 'schedule_id': q['schedule_id'], 'policy_revision': 1,
            'rounding': q['rounding'], 'status': 'valid'}
    if datetime.now(timezone.utc) >= result['expires_at']:
        raise PublicError('quote_expired', 'Review a current quote.', status=409)
    return result
