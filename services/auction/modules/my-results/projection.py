"""Read-only current source projection. This module cannot allocate or release."""
import re
from datetime import datetime
from uuid import UUID

MAX_MINOR = 9_000_000_000_000_000
UTC_INSTANT = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)')


def _utc_instant(value):
    if not isinstance(value, str) or not UTC_INSTANT.fullmatch(value):
        raise ValueError('invalid_instant')
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('invalid_instant') from None
    return value.removesuffix('+00:00') + 'Z' if value.endswith('+00:00') else value


def _reference(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError('invalid_reference')
    reference = UUID(value)
    if str(reference) != value.lower():
        raise ValueError('invalid_reference')
    return reference


def project(source, authority):
    if (authority.get('allowed') is not True or 'organization_id' not in authority
            or authority['organization_id'] is not None):
        raise PermissionError('denied')
    buyer = _reference(source.get('buyer_id'))
    try:
        actor = _reference(authority.get('actor_id'))
    except ValueError:
        raise PermissionError('denied') from None
    if buyer != actor:
        raise PermissionError('denied')
    expected_revision = authority.get('expected_source_revision')
    for revision in (expected_revision, source.get('revision'), source.get('source_revision')):
        if type(revision) is not int or revision < 1:
            raise ValueError('invalid_revision')
    if source['source_revision'] != expected_revision:
        raise ValueError('stale')
    for key in ('auction_id', 'watch_id', 'listing_id'):
        _reference(source.get(key))
    if (source.get('currency') != 'USD' or source.get('result_recorded') is not True
            or source.get('participated') is not True):
        raise ValueError('unavailable')
    ended_at = _utc_instant(source.get('ended_at'))
    if type(source.get('is_demo')) is not bool:
        raise ValueError('missing_demo_fact')
    amount = source.get('final_minor')
    if amount is not None and (type(amount) is not int or not 1 <= amount <= MAX_MINOR):
        raise ValueError('invalid_minor_units')
    qualified = source.get('sale_qualified')
    if type(qualified) is not bool:
        raise ValueError('invalid_result')
    winner, order = source.get('winner_id'), source.get('order_id')
    if order is not None:
        _reference(order)
    financial = source.get('financial_state')
    denied = source.get('allocation_state') == 'denied'
    if ('allocation_state' in source and not denied) or (denied and (not qualified or order is not None or financial is not None)):
        raise ValueError('invalid_allocation_outcome')
    if not qualified:
        if winner is not None or order is not None or financial not in (None, 'pending'):
            raise ValueError('inconsistent_no_sale')
        state = 'no_sale'
    else:
        if not denied and financial not in ('pending', 'unknown', 'unpaid', 'unpaid_released', 'paid_held', 'released'):
            raise ValueError('invalid_financial_state')
        winner = _reference(winner)
        if amount is None:
            raise ValueError('invalid_winner')
        if not denied and financial != 'pending' and order is None:
            raise ValueError('missing_order')
        state = 'won' if winner == buyer else 'lost'
    # A competing buyer never receives another buyer's order reference.
    own_order = order if winner == buyer else None
    own_financial = financial if winner == buyer else None
    next_action = (
        'contact_support' if own_financial == 'unknown' or (state == 'won' and own_order is None) else
        'review_order' if own_order else 'view_auction'
    )
    return dict(is_demo=source['is_demo'], auction_id=source['auction_id'], watch_id=source['watch_id'],
                listing_id=source['listing_id'], buyer_id=str(buyer), revision=source['revision'], state=state,
                currency='USD', final_minor=amount, ended_at=ended_at,
                order_id=own_order, completed_sale=qualified and financial == 'released',
                financial_state=own_financial, next_action=next_action,
                **({'allocation_state': 'denied'} if denied else {}))
