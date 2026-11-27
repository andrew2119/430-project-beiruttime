"""UTC retention decisions; source facts remain authoritative."""
from datetime import datetime, timedelta, timezone

REASONS = frozenset({'active_sale', 'custody', 'payout', 'dispute', 'financial', 'audit', 'active_case'})
DOMAINS = ('identity', 'catalog', 'auction', 'pricing', 'orders', 'eligibility', 'service-operations', 'communications', 'trust')


def instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError('invalid')
    return value.astimezone(timezone.utc)


def stamp(value):
    return instant(value).isoformat().replace('+00:00', 'Z')


def anniversary(value):
    value = instant(value)
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)


def cleanup_due(kind, created_at, final_review_at=None, active_case=False):
    created_at = instant(created_at)
    if kind == 'unsubmitted':
        return created_at + timedelta(days=7)
    if kind == 'proof':
        return None if active_case or final_review_at is None else instant(final_review_at) + timedelta(days=30)
    if kind == 'audit':
        return None if active_case else anniversary(created_at)
    raise ValueError('invalid')


def removable(now, due_at):
    return due_at is not None and instant(now) >= instant(due_at)
