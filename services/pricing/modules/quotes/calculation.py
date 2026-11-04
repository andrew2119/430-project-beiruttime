"""Q01: explicit sample policy, integer arithmetic and a retained commission basis."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from bt_contracts.pricing.quotes.models import QuoteRequest


def percentage(minor: int, basis_points: int) -> int:
    return (minor * basis_points + 5000) // 10000


def calculate(body: QuoteRequest, owner_id, now=None, *, source_verified=False):
    now = now or datetime.now(timezone.utc)
    buyer_fee = percentage(body.price_minor, 300)
    commission = percentage(body.price_minor, 500)
    return {**body.model_dump(mode='json'), 'id': str(uuid4()), 'owner_id': str(owner_id),
        'revision': 1, 'minor_unit_exponent': {'USD': 2, 'LBP': 2}[body.currency],
        'buyer_fee_minor': buyer_fee, 'seller_commission_minor': commission,
        'seller_net_minor': body.price_minor - commission, 'shipping_minor': 0, 'tax_minor': 0,
        'payable_minor': body.price_minor + buyer_fee, 'sample': True, 'rounding': 'half_up',
        'source_verified': source_verified,
        'fx': None, 'commission_basis': 'price_excluding_buyer_fee_shipping_tax',
        'policy': {'buyer_fee_bps': 300, 'seller_commission_bps': 500,
                   'shipping': 'sample_zero', 'tax': 'sample_zero', 'fx': 'not_applied',
                   'currency_exponents': {'USD': 2, 'LBP': 2}},
        'created_at': now.isoformat(), 'expires_at': (now + timedelta(minutes=15)).isoformat(), 'reviewed_at': None}
