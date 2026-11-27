"""Current watch offer economics and fail-closed handling of historical terms."""
from bt_contracts_core.errors import PublicError


def is_current(snapshot):
    return (isinstance(snapshot, dict) and snapshot.get('purpose') == 'offer'
            and snapshot.get('currency') == 'USD' and snapshot.get('schedule_id') == 'usd-v2'
            and isinstance(snapshot.get('policy'), dict) and type(snapshot['policy'].get('revision')) is int
            and snapshot['policy']['revision'] == 2)


def require_current(snapshot, *, state, has_intent=False):
    if is_current(snapshot):
        return snapshot
    if state in ('acceptance_pending', 'accepted') or (has_intent and state != 'lost'):
        raise PublicError('legacy_reconciliation', 'Legacy offer terms require recorded reconciliation.', status=409,
                          details={'next_action': 'recorded_reconciliation'})
    raise PublicError('fee_review_required', 'Review fresh USD terms before making a new offer.', status=409,
                      details={'next_action': 'review_current_quote'})
