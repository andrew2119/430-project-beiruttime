"""Strict acknowledgements for the published Auction v3 edit handshake."""
from datetime import datetime


def matches(value, op, row, phase):
    if not isinstance(value, dict):
        return False
    expected = op['base_revision'] + (1 if phase == 'committed' else 0)
    if not (
        value.get('status') == 'succeeded' and value.get('phase') == phase
        and value.get('operation_id') == str(op['id'])
        and value.get('listing_id') == str(row['id'])
        and value.get('watch_id') == str(row['physical_watch_id'])
        and type(value.get('listing_revision')) is int
        and value['listing_revision'] == expected
    ):
        return False
    if phase != 'committed' and (
        type(value.get('next_revision')) is not int
        or value['next_revision'] != op['base_revision'] + 1
    ):
        return False
    if phase == 'aborted':
        return value.get('code') in ('prepare_expired', 'orders_denied')
    if op['auction_protocol'] == 3 and phase in ('prepared', 'dispatched'):
        if not (
            type(value.get('protocol')) is int and value['protocol'] == 3
            and value.get('orders_operation_key') == str(op['id'])
            and type(value.get('orders_expected_revision')) is int
            and value['orders_expected_revision'] == op['orders_revision']
        ):
            return False
        try:
            expiry = datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00'))
            if expiry.tzinfo is None:
                return False
        except (KeyError, ValueError, TypeError, AttributeError):
            return False
        # Only Auction's dispatch CAS decides expiry. Never infer permission or
        # cancellation from this local process's clock, a timeout, or a 404.
    return True
