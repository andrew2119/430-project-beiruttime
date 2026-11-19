"""Refund planning uses only current facts fenced by the single Orders journal."""
from datetime import datetime, timedelta, timezone
from bt_contracts.orders.refunds.v1 import Authority, Command, Facts, Plan


class Refused(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def scope(command: Command, authority: Authority):
    if not authority.can_refund or not authority.current_assignment or any(
        getattr(command, field) != getattr(authority, field)
        for field in ('actor_id', 'organization_id', 'subject_id', 'watch_id')
    ):
        raise Refused('denied')


def plan(command: Command, facts: Facts, authority: Authority, now: datetime) -> Plan:
    scope(command, authority)
    if now.tzinfo is None or now.utcoffset() is None:
        raise Refused('unavailable')
    if any(getattr(command, field) != getattr(facts, field) for field in (
        'subject_id', 'watch_id', 'organization_id', 'quote_id', 'quote_revision',
        'policy_revision', 'basis_id', 'source_revision'
    )) or command.expected_revision != facts.revision:
        raise Refused('stale')
    if facts.payment_state != 'paid_held':
        raise Refused('basis_required')
    if not facts.basis_approved or now >= facts.basis_valid_until:
        raise Refused('basis_required')
    if facts.basis == 'failed_authentication':
        if facts.kind != 'watch' or not facts.private_sale or not facts.failed_inspection:
            raise Refused('basis_required')
    elif facts.custody_transferred and not (
        facts.controlled_return_received or facts.recorded_failure_exception
    ):
        raise Refused('return_required')
    cap = min(facts.paid_principal_minor, facts.retained_principal_minor, facts.approved_minor)
    if facts.basis == 'partial_work':
        if facts.kind != 'job':
            raise Refused('basis_required')
        partial = sum(line.amount_minor for line in facts.lines if line.accepted and
                      not line.performed_or_consumed and (line.kind == 'labor' or
                      (line.kind == 'part' and line.unused_returnable)))
        cap = min(cap, partial)
    if facts.confirmed_minor + facts.unresolved_minor + command.amount_minor > cap:
        raise Refused('cap_exceeded')
    now = now.astimezone(timezone.utc)
    return Plan(command=command, buyer_id=facts.buyer_id, cap_minor=cap,
                business_fee_receivable_minor=facts.business_fee_minor if facts.kind == 'job' else 0,
                fee_collection_key=f'job-fee:{facts.subject_id}:{facts.quote_id}',
                recorded_at=now, next_review_at=now + timedelta(hours=24))
