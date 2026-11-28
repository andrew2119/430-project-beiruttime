"""Synthetic deterministic boundary examples, never execution authorization."""
from datetime import datetime, timezone, timedelta
from uuid import UUID

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
def identity(number):
    return UUID(int=number)

def command():
    return dict(schema_version='authorized-work.v1', operation_id=identity(1), subject_id=identity(2),
        watch_id=identity(3), actor_id=identity(4), organization_id=identity(5), expected_revision=0,
        source_revision=1, quote_id=identity(6), quote_revision=1, policy_revision=1, kind='progress',
        line_ids=[identity(7)], parts=[], readings=[dict(phase='before', observed_at=NOW,
        seconds_per_day=12, method='Timing instrument')], note='Synthetic observation', observed_at=NOW,
        next_actor=identity(4), next_action='Check actual work', next_review_at=NOW+timedelta(hours=1))

def authority():
    return {**{k:v for k,v in command().items() if k in ('actor_id','organization_id','subject_id','watch_id',
        'source_revision','quote_id','quote_revision','policy_revision')}, 'accepted_line_ids':[identity(7)],
        'responsible_actor_id':identity(4), 'required_line_ids':[identity(7)], 'state':'authorized', 'valid_until':NOW+timedelta(hours=2),
        'custody_current':True, 'payment_state':'paid_held', 'commitment_current':True}

OUTCOMES = {
    'success': {'state':'recorded','revision':1},
    'denied': {'error':'denied','writes':0},
    'stale': {'error':'stale','writes':0},
    'lost_response': {'state':'pending','pending_reason':'orders_hold','retry_same_operation':True},
}
