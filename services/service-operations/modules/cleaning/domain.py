"""Pure decisions over current, source-serialized facts."""
from datetime import timedelta
from bt_contracts.service.cleaning.v1 import Result


class Denied(Exception):
    def __init__(self, code):
        self.code = code


def authority(facts, actor, subject):
    if not facts.authorized or not facts.supported or facts.actor_id != actor or facts.subject_id != subject:
        raise Denied('denied')


def quote_valid(quote, record, facts, now, *, retained=False):
    if quote is None:
        raise Denied('assessment_required')
    if (quote.request_id != facts.subject_id or quote.buyer_id != facts.actor_id or quote.watch_id != facts.watch_id
            or quote.organization_id != facts.organization_id or quote.request_revision != record.revision
            or quote.assessor_id == quote.approver_id or set(quote.areas) != set(record.areas)
            or quote.condition != record.condition or quote.preservation_limits != record.preservation_limits
            or not all(text.strip() for text in (quote.process, quote.limitations, quote.lead_time, quote.terms))
            or quote.base_minor != quote.total_minor or quote.buyer_fee_minor != 0
            or quote.business_fee_minor != (quote.base_minor * 5 + 50) // 100):
        raise Denied('stale_quote')
    if retained:
        if quote.expires_at is not None or quote.accepted_at is None or quote.accepted_at > now:
            raise Denied('retention_required')
    elif quote.expires_at is None:
        if quote.accepted_at is None or quote.accepted_at > now:
            raise Denied('stale_quote')
    elif now >= quote.expires_at:
        raise Denied('quote_expired')


def decide(command, record, facts, now):
    authority(facts, command.actor_id, command.subject_id)
    if (command.watch_id != facts.watch_id or command.organization_id != facts.organization_id
            or command.source_revision != facts.source_revision or command.policy_revision != facts.policy_revision):
        raise Denied('stale_source')
    if command.expected_revision != (record.revision if record else 0):
        raise Denied('stale_revision')
    if record and (record.watch_id != command.watch_id or record.actor_id != command.actor_id
                   or record.organization_id != command.organization_id):
        raise Denied('denied')
    if record and record.state == 'accepted':
        raise Denied('accepted_scope_locked')
    quote = None
    if command.action == 'accept':
        if record is None:
            raise Denied('request_required')
        if (command.areas != record.areas or command.condition != record.condition
                or command.preservation_limits != record.preservation_limits
                or record.source_revision != facts.source_revision or record.policy_revision != facts.policy_revision):
            raise Denied('stale_revision')
        quote = facts.quote
        quote_valid(quote, record, facts, now)
        if (command.quote_id != quote.quote_id or command.quote_revision != quote.quote_revision
                or command.terms_revision != quote.terms_revision):
            raise Denied('stale_quote')
    elif any(value is not None for value in (command.quote_id, command.quote_revision, command.terms_revision)):
        raise Denied('invalid_request')
    return Result(**command.model_dump(exclude={'action', 'assessment_permission', 'no_submersion_promise',
                  'no_movement_service', 'quote_id', 'quote_revision', 'terms_revision'}),
                  state='accepted' if quote else 'requested', revision=command.expected_revision + 1,
                  next_actor='business', next_review_at=now + timedelta(hours=24), quote=quote,
                  accepted_at=now if quote else None, submitted_at=record.submitted_at if record else now)


def readiness(record, facts, now):
    if record is None or record.state != 'accepted' or record.quote is None:
        raise Denied('acceptance_required')
    if (record.source_revision != facts.source_revision or record.policy_revision != facts.policy_revision
            or record.watch_id != facts.watch_id or record.organization_id != facts.organization_id
            or record.actor_id != facts.actor_id):
        raise Denied('stale_source')
    # The assessed quote references the preceding request revision, not the acceptance receipt revision.
    request = record.model_copy(update={'revision': record.quote.request_revision})
    quote_valid(facts.quote, request, facts, now, retained=True)
    accepted = record.quote.model_dump(exclude={'expires_at', 'accepted_at'})
    current = facts.quote.model_dump(exclude={'expires_at', 'accepted_at'})
    if accepted != current:
        raise Denied('stale_quote')
    if not all((facts.order_id, facts.job_id, facts.commitment_id, facts.custody_receipt_id,
                facts.payment_operation_id, facts.payment_revision, facts.paid_held,
                facts.current_custody, facts.current_consent)) or facts.incident:
        raise Denied('execution_prerequisites')
    payment = facts.payment
    if (payment is None or payment.state != 'paid_held' or payment.buyer_id != facts.actor_id
            or payment.order_id != facts.order_id or payment.watch_id != facts.watch_id
            or payment.quote_id != record.quote.quote_id or payment.quote_revision != record.quote.quote_revision
            or payment.total_minor != record.quote.total_minor or payment.payment_operation_id != facts.payment_operation_id
            or payment.payment_revision != facts.payment_revision
            or facts.custody_order_id != facts.order_id or facts.custody_watch_id != facts.watch_id
            or facts.commitment_order_id != facts.order_id or facts.commitment_watch_id != facts.watch_id):
        raise Denied('execution_prerequisites')
    return {'ready': True, 'revision': record.revision, 'job_id': str(facts.job_id),
            'quote_id': str(record.quote.quote_id), 'quote_revision': record.quote.quote_revision}
