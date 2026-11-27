"""Current evidence predicates shared by intake consumers."""
from datetime import datetime

from bt_contracts.service.intake.current import PaidReadiness


def diagnostic_opening_allowed(*, receipt, watch_id, watch_revision, organization_id,
                               incident_revision, now: datetime, assigned, permission,
                               opening_permission, fee_acknowledged, no_polish_acknowledged):
    return bool(assigned and permission and opening_permission and fee_acknowledged
        and no_polish_acknowledged and receipt and receipt['watch_id'] == watch_id
        and receipt['watch_revision'] == watch_revision
        and receipt['organization_id'] == organization_id
        and receipt['incident_revision'] == incident_revision
        and receipt['current'] is True and receipt['received_at'] <= now)


def execution_allowed(*, accepted_scope_revision, current_scope_revision, custody_current,
                      payment, buyer_id, order_id, watch_id, quote_id, quote_revision, total_minor):
    if (custody_current is not True or type(accepted_scope_revision) is not int
            or type(current_scope_revision) is not int or accepted_scope_revision <= 0
            or accepted_scope_revision != current_scope_revision
            or type(quote_revision) is not int or type(total_minor) is not int):
        return False
    try:
        readiness = PaidReadiness.model_validate(payment)
    except ValueError:
        return False
    return (readiness.state == 'paid_held'
            and (readiness.buyer_id, readiness.order_id, readiness.watch_id,
                 readiness.quote_id, readiness.quote_revision, readiness.total_minor)
            == (buyer_id, order_id, watch_id, quote_id, quote_revision, total_minor))
