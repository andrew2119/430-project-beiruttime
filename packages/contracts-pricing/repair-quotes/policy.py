"""Repair consent binds current diagnosed lines; it never authorizes execution."""
from bt_contracts_core.errors import PublicError
from bt_contracts.pricing.quotes.assessed import AssessedScopeLine


def current_scope(snapshot, source):
    if (source['buyer_id'] != snapshot['buyer_id']
            or source['organization_id'] != snapshot['organization_id']
            or source['diagnosis'] != snapshot['diagnosis']):
        raise PublicError('source_changed', 'Review the current diagnosis and a new quote.', status=409)
    retained = {line['id']: AssessedScopeLine.model_validate(
        {key: value for key, value in line.items() if key != 'amount_minor'}
    ).model_dump(mode='json') for line in snapshot['lines']}
    current = {line['id']: line for line in source['lines']}
    if retained != current:
        raise PublicError('scope_mismatch', 'Review the current parts and mandatory lines in a new quote.', status=409)


def decision_binding(row, snapshot, body, *, accepting, now):
    if body.quote_revision != row['revision'] or body.terms_digest != snapshot['terms_digest']:
        raise PublicError('quote_binding_mismatch', 'Review the exact quote revision and terms.', status=409)
    if row['state'] != 'issued':
        raise PublicError('quote_not_current', 'Review the current quote or retained decision.', status=409)
    if accepting and now >= row['expires_at']:
        raise PublicError('quote_expired', 'The quote expired; request a new quote or decline work.', status=409)
    if accepting and snapshot['assessment_fee_minor'] and not body.accept_assessment_fee:
        raise PublicError('fee_consent_required', 'Explicitly accept the disclosed assessment fee.', status=409)
