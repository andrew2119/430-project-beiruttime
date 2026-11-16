"""Orders-only retained exact economics. Reading history is never allocation authority."""
from uuid import UUID
from fastapi import APIRouter, Request
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts.pricing.quotes.current import RetainedFinancialQuote
from service_app import peers
from service_app.current import POLICY, decoded, require_usd

router = APIRouter()


@router.get('/internal/v3/quotes/{quote_id}/retained', response_model=RetainedFinancialQuote)
@router.get('/internal/v2/quotes/{quote_id}/retained', response_model=RetainedFinancialQuote)
async def retained(quote_id: UUID, buyer_id: UUID, request: Request):
    peers.service(request, {'orders'})
    async with request.app.state.pool.acquire() as tx:
        original = await tx.fetchrow('SELECT * FROM l07_quotes WHERE id=$1', quote_id)
        auction = await tx.fetchrow('SELECT * FROM l14_auction_quotes WHERE id=$1', quote_id)
        assessed = await tx.fetchrow('SELECT * FROM l14_assessed_quotes WHERE id=$1', quote_id)
        decision = await tx.fetchrow('SELECT * FROM l14_quote_decisions WHERE quote_id=$1', quote_id) if assessed else None
        commitment = await tx.fetchrow('SELECT * FROM l14_quote_commitments WHERE quote_id=$1', quote_id)
        offer = await tx.fetchrow('SELECT * FROM l14_offers WHERE quote_id=$1', quote_id)
    if original or auction:
        row = original or auction
        q = decoded(row['snapshot'])
        require_usd(q)
        committed = bool(commitment or (auction and auction['kind'] == 'winner')
                         or (offer and offer['state'] in ('acceptance_pending', 'accepted')))
        owner = original['owner_id'] if original else auction['buyer_id']
        if owner != buyer_id:
            raise AccessDenied('Wrong retained quote subject')
        financial = {key: q[key] for key in ('currency', 'price_minor', 'buyer_fee_minor', 'seller_commission_minor',
            'seller_net_minor', 'shipping_minor', 'tax_minor', 'payable_minor', 'schedule_id', 'rounding', 'minor_unit_exponent', 'sample')}
        return {**financial, 'quote_id': str(quote_id), 'quote_revision': q['revision'], 'buyer_id': str(buyer_id),
            'source_id': q['subject_id'], 'source_revision': q['subject_revision'],
            'policy_revision': q['policy'].get('revision', 1), 'policy': q['policy'],
            'expires_at': None if committed else row['expires_at'].isoformat(),
            'reviewed_at': row['reviewed_at'].isoformat() if row['reviewed_at'] else None,
            'authority': 'retained_read_only'}
    if assessed:
        if assessed['buyer_id'] != buyer_id:
            raise AccessDenied('Wrong retained quote subject')
        q = decoded(assessed['snapshot'])
        require_usd(q)
        accepted = bool(decision and decision['decision'] == 'accepted')
        totals = decoded(decision['amounts']) if accepted else q['full_total']
        return {'quote_id': str(quote_id), 'quote_revision': assessed['revision'], 'buyer_id': str(buyer_id),
            'source_id': str(assessed['source_id']), 'source_revision': assessed['source_revision'],
            'currency': q['currency'], 'price_minor': totals['parts_minor'] + totals['labor_minor'] + totals['assessment_fee_minor'],
            'buyer_fee_minor': 0 if q['policy'].get('revision') == 2 else totals['platform_fee_minor'],
            'seller_commission_minor': totals['seller_commission_minor'],
            'seller_net_minor': totals['seller_net_minor'], 'shipping_minor': 0, 'tax_minor': 0,
            'payable_minor': totals['payable_minor'], 'schedule_id': q['schedule_id'], 'rounding': POLICY['rounding'],
            'minor_unit_exponent': 2, 'sample': True, 'policy_revision': q['policy']['revision'], 'policy': q['policy'],
            'expires_at': None if accepted else assessed['expires_at'].isoformat(), 'reviewed_at': decision['decided_at'].isoformat() if accepted else None,
            'selected_line_ids': decoded(decision['selected_line_ids']) if accepted else [],
            'terms_digest': q['terms_digest'], 'state': assessed['state'], 'return_fee_minor': q['return_fee_minor'],
            'accepted_fee_lines': decoded(decision['accepted_fee_lines']) if decision else {},
            'authority': 'retained_read_only'}
    raise PublicError('not_found', 'Retained quote not found.', status=404)
