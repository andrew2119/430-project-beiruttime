"""S02 accepted repair to O03 paid scope; no customization decision."""
from dataclasses import replace

def repair_binding(command, acceptance):
    """Freeze accepted scope before payment; use this same command for lookup."""
    return replace(command, kind='repair', service_acceptance_id=acceptance.acceptance_id,
                   service_total_minor=acceptance.total_minor)


async def authorize_service(coordinator, command, acceptance, payment):
    """Arguments are authenticated current producer responses, never form values."""
    command = repair_binding(command, acceptance)
    expected = (command.subject_id, command.watch_id, command.quote_id, command.quote_revision)
    if (acceptance.buyer_id, acceptance.watch_id, acceptance.quote_id, acceptance.quote_revision) != expected:
        return await coordinator.held(command, 'denied', 'scope')
    if (payment.buyer_id, payment.watch_id, payment.quote_id, payment.quote_revision) != expected:
        return await coordinator.held(command, 'denied', 'scope')
    if (acceptance.organization_id != command.organization_id or acceptance.revision != command.expected_revision
            or not acceptance.acceptance_id or acceptance.accepted is not True):
        return await coordinator.held(command, 'stale', 'revision')
    if (payment.order_kind != 'service' or payment.currency != 'USD'
            or type(payment.total_minor) is not int or payment.total_minor != acceptance.total_minor
            or payment.total_minor <= 0 or not payment.order_id
            or not payment.payment_operation_id or type(payment.payment_revision) is not int or payment.payment_revision < 1
            or payment.state != 'paid_held'):
        return await coordinator.held(command, 'pending', 'payment_reconciliation')
    # The canonical final operation rechecks these source facts under serialization.
    return await coordinator.authorize(command)
