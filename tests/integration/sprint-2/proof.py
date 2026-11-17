"""Local contract preparation. No network access or connected certification."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

SCHEMA = 'l25.operation.v1'
FIELDS = {'schema_version', 'operation_id', 'subject_id', 'watch_id', 'actor_id',
          'organization_id', 'expected_revision', 'state', 'revision',
          'pending_reason', 'next_actor', 'next_review_at'}
STATES = {'success', 'denied', 'stale', 'pending', 'unavailable'}
UTC = timezone.utc


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError('UTC instant required')
    return result


def minor(value):
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ValueError('finite nonnegative integer cents required')
    return value


def validate(row):
    if set(row) != FIELDS or row['schema_version'] != SCHEMA:
        raise ValueError('unexpected envelope')
    for key in ('operation_id', 'subject_id', 'watch_id', 'actor_id'):
        if not isinstance(row[key], str) or not 1 <= len(row[key]) <= 128:
            raise ValueError('bounded binding required')
    if row['organization_id'] is not None and (
        not isinstance(row['organization_id'], str)
        or not 1 <= len(row['organization_id']) <= 128
    ):
        raise ValueError('bounded organization required')
    for key in ('expected_revision', 'revision'):
        if type(row[key]) is not int or row[key] < 1:
            raise ValueError('positive revision required')
    if row['state'] not in STATES:
        raise ValueError('unknown outcome')
    if row['state'] in {'pending', 'unavailable'}:
        if not all(row[k] for k in ('pending_reason', 'next_actor', 'next_review_at')):
            raise ValueError('responsible follow-up required')
        instant(row['next_review_at'])
    return deepcopy(row)


def fixture(state):
    """Synthetic response envelopes only; never funds, passes or work."""
    row = dict(schema_version=SCHEMA, operation_id='sample-operation-1',
               subject_id='sample-buyer', watch_id='sample-watch',
               actor_id='sample-buyer', organization_id=None,
               expected_revision=1, state=state, revision=1,
               pending_reason=None, next_actor=None, next_review_at=None)
    if state in {'pending', 'unavailable'}:
        row.update(pending_reason='source_unavailable', next_actor='sample-operator',
                   next_review_at='2026-11-18T00:00:00Z')
    return validate(row)


def payment_deadline(notified_at, method, attempt_at=None):
    """Frozen clock expectation; not payment admission authority."""
    if method not in {None, 'card', 'Whish Money', 'OMT Pay'}:
        raise ValueError('unsupported simulated method')
    if notified_at is None:
        return None
    deadline = instant(notified_at) + timedelta(hours=24 if method == 'card' else 48)
    if attempt_at is not None:
        if instant(attempt_at) < instant(notified_at):
            raise ValueError('attempt precedes notice')
        if instant(attempt_at) < deadline:
            deadline += timedelta(hours=24)
    return deadline


ROUTES = {
    'private_purchase': ('commit', 'notice', 'payment_held', 'expert_receipt',
                         'independent_pass', 'buyer_receipt', 'window_elapsed', 'release'),
    'dealer_purchase': ('commit', 'notice', 'payment_held', 'business_assurance',
                        'buyer_receipt', 'window_elapsed', 'release'),
    'brand_purchase': ('commit', 'notice', 'payment_held', 'business_assurance',
                       'buyer_receipt', 'window_elapsed', 'release'),
    'customization': ('five_snapshots', 'assessment', 'quote_acceptance', 'consent',
                      'independent_eligibility', 'brand_approval', 'payment_held',
                      'payment_readiness', 'watch_allocation', 'production', 'quality',
                      'buyer_receipt', 'window_elapsed', 'release'),
    'dealer_service': ('custody_receipt', 'diagnosis', 'quote_acceptance', 'payment_held',
                       'work', 'quality', 'buyer_receipt', 'window_elapsed', 'release'),
    'brand_service': ('custody_receipt', 'diagnosis', 'quote_acceptance', 'payment_held',
                      'work', 'quality', 'buyer_receipt', 'window_elapsed', 'release'),
}


@dataclass(frozen=True)
class Observation:
    step: str
    receipt: dict
    source: str


def verify_route(route, observations):
    """Check bounded provider observations; return no private payloads."""
    expected = ROUTES[route]
    if len(observations) != len(expected):
        raise ValueError('missing or extra source operation')
    binding = None
    for step, observation in zip(expected, observations):
        if observation.step != step or observation.source != 'provider_operation':
            raise ValueError('actual ordered source operations required')
        row = validate(observation.receipt)
        current = tuple(row[k] for k in ('subject_id', 'watch_id', 'organization_id'))
        if binding is None:
            binding = current
        if current != binding or row['state'] != 'success':
            raise ValueError('scope mismatch or unresolved prerequisite')
        if row['revision'] < row['expected_revision']:
            raise ValueError('stale source revision')
    return {'route': route, 'status': 'observations_validated',
            'connected_acceptance': 'deferred'}


def preparation_record():
    manifest = json.loads(Path(__file__).with_name('manifest.json').read_text())
    return {'schema_version': 'l25.result.v1', 'result': 'prepared',
            'connected_passes': 0, 'fixture_passes_are_integration': False,
            'remaining': [{'journey': j['id'], 'case': case, 'status': 'deferred'}
                          for j in manifest['journeys'] for case in j['cases']],
            'separate_machine': ['database', 'signed_simulated_callbacks',
                                 'concurrency', 'restart', 'display_matrix',
                                 'physical_phone', 'independent_review']}


if __name__ == '__main__':
    print(json.dumps(preparation_record(), indent=2))
