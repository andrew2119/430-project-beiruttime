"""Decisions executed only inside the canonical provider transaction."""
from datetime import timedelta, timezone
from uuid import uuid5, NAMESPACE_URL
from bt_contracts.pricing.counteroffers.current import Command, Offer, Authority, Facts, Result


def decide(command: Command, current: Offer, authority: Authority, facts: Facts, now):
    """Return result and replacement; provider commits history and receipt atomically."""
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError('Authoritative UTC time required')
    def result(state, code, replacement=None):
        value = replacement or current
        return Result(**command.model_dump(include={'operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision'}), state=state, code=code,
                      revision=value.revision, current=value if state != 'denied' else None,
                      next_actor='support' if state == 'pending' else ('buyer' if value.state == 'sent' else 'seller'),
                      pending_reason='allocation_required' if state == 'pending' else None,
                      next_review_at=now + timedelta(hours=24) if state == 'pending' else None), replacement
    if (not authority.permitted or authority.actor_id != command.actor_id
            or authority.organization_id != command.organization_id
            or current.organization_id != command.organization_id
            or command.actor_id not in (current.buyer_id, current.seller_id)
            or current.buyer_id == current.seller_id):
        return result('denied', 'denied')
    if (command.subject_id != current.subject_id or command.watch_id != current.watch_id
            or facts.watch_id != current.watch_id or facts.subject_id != current.subject_id):
        return result('denied', 'denied')
    if (command.expected_revision != current.revision
            or command.source_revision != facts.source_revision
            or command.authority_revision != authority.scope_revision):
        return result('denied', 'stale_revision')
    if current.state != 'sent':
        return result('denied', 'closed')
    if now >= current.expires_at or not facts.available:
        closed = current.model_copy(update={'state': 'closed', 'revision': current.revision + 1})
        return result('succeeded', 'closed', closed)
    if facts.mode == 'auction' or facts.blocked:
        return result('denied', 'denied')
    seller = command.kind == 'propose'
    if command.actor_id != (current.seller_id if seller else current.buyer_id):
        return result('denied', 'denied')
    if seller and not authority.seller_approved:
        return result('denied', 'denied')
    if command.kind == 'reject':
        rejected = current.model_copy(update={'state': 'rejected', 'revision': current.revision + 1})
        return result('succeeded', 'rejected', rejected)
    if not facts.quote_current:
        return result('denied', 'review_current_fees')
    economics = command.economics
    if economics != facts.economics or (not seller and economics != current.economics):
        return result('denied', 'review_current_fees')
    price = economics.price_minor
    if (economics.buyer_fee_minor != (price * 3 + 50) // 100
            or economics.seller_commission_minor != (price * 5 + 50) // 100
            or economics.total_minor != price + economics.buyer_fee_minor):
        return result('denied', 'review_current_fees')
    if seller:
        counter = current.model_copy(update={
            'id': uuid5(NAMESPACE_URL, 'counteroffers.v1:' + str(command.operation_id)),
            'revision': current.revision + 1, 'predecessor_id': current.id,
            'economics': economics, 'sent_at': now.astimezone(timezone.utc),
            'expires_at': now + timedelta(hours=48)})
        return result('succeeded', 'superseded', counter)
    if command.reviewed_revision != current.revision:
        return result('denied', 'review_current_fees')
    # This decision requests allocation; it never claims reservation itself.
    return result('pending', 'allocation_required')
