"""Pure policy over current locked facts; no money or stock authority."""
from datetime import timedelta
from bt_contracts.orders.cancellations.v1 import Result


def decide(command, facts, actor_id, now):
    value = dict(operation_id=command.operation_id, subject_id=command.subject_id,
                 watch_id=command.watch_id, actor_id=actor_id,
                 organization_id=command.organization_id,
                 expected_revision=command.expected_revision, revision=facts.revision,
                 state='denied', pending_reason=None, next_actor=None,
                 next_review_at=None, effect='none', refundable_minor=0, completed=False)

    def result(state, reason=None, effect='none', refundable=0, completed=False):
        held = state == 'pending' or effect == 'pause_fulfilment'
        started = (facts.hold_started_at or now) if held else None
        progress = facts.last_progress_at if held else None
        anchor = (progress or started) if held else None
        review_at = anchor + timedelta(hours=24) if held else None
        escalation_at = anchor + timedelta(hours=48) if held else None
        escalated = held and now >= escalation_at
        return Result(**(value | dict(state=state, pending_reason=reason, effect=effect,
            refundable_minor=refundable, completed=completed,
            next_actor=(facts.escalation_actor if escalated else facts.responsible_actor) if held else None,
            next_review_at=review_at, hold_started_at=started, last_progress_at=progress,
            escalation_at=escalation_at, review_overdue=held and now >= review_at,
            escalated=escalated)))

    if (command.subject_id != facts.subject_id or command.watch_id != facts.watch_id
            or command.organization_id != facts.organization_id):
        return result('denied', 'scope')
    if command.expected_revision != facts.revision:
        return result('denied', 'stale_revision')
    if facts.cancellation_state in ('accepted', 'declined'):
        return result('denied', 'already_decided')
    if command.action != 'request' and facts.cancellation_state != 'pending':
        return result('denied', 'request_required')
    value['revision'] += 1
    if command.action == 'decline':
        return result('declined', 'decision_recorded')
    if facts.payment == 'released':
        return result('pending', 'settlement_review', 'pause_fulfilment')
    uncertain = facts.payment in ('pending', 'unknown') or any(
        attempt != 'declined' for attempt in facts.attempts)
    if facts.payment == 'unpaid':
        if uncertain or facts.work_started or facts.parts_consumed or facts.dispatched or facts.custody_transferred:
            return result('pending', 'source_review', 'pause_fulfilment')
        return result('accepted', effect='release_commitment', completed=True)
    if facts.payment != 'paid_held':
        return result('pending', 'payment_review', 'pause_fulfilment')
    if any(attempt in ('pending', 'unknown') for attempt in facts.attempts):
        return result('pending', 'payment_review', 'pause_fulfilment')
    if ((facts.custody_transferred or facts.dispatched)
            and facts.return_state != 'verified' and not facts.failure_exception_id):
        return result('pending', 'return_pending', 'pause_fulfilment')
    if command.action == 'request':
        return result('pending', 'decision_required', 'pause_fulfilment')
    basis = facts.principal_minor if facts.kind == 'watch' else min(
        facts.principal_minor, facts.refundable_labor_minor + facts.unused_returnable_parts_minor)
    remaining = max(0, basis - facts.reserved_refund_minor - facts.confirmed_refund_minor)
    return result('accepted', 'refund_review', 'pause_fulfilment', remaining)
