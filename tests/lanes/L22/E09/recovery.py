"""Release preparation contracts. Does not execute release operations."""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
VERSION = 'L22.E09.v1'
DOMAINS = ('identity', 'catalog', 'auction', 'pricing', 'orders',
           'eligibility', 'trust', 'communications', 'service-operations')
JOURNEYS = ('purchase', 'auction', 'five-dimension', 'customization',
            'maintenance', 'repair', 'cleaning', 'polishing', 'enlargement',
            'reduction', 'return', 'refund')
CASES = ('positive', 'denied', 'stale', 'cross-account', 'timeout',
         'lost-response', 'duplicate', 'restart', 'before', 'equal', 'after')
OWNERS = ('identity-scope', 'competition-commitment', 'economics-money',
          'custody-quality', 'experience-recovery')
OPERATIONS = {
    'quote.validate.v3': ('pricing', 'GET', '/internal/v3/quotes/{id}/validation'),
    'quote.retained.v3': ('pricing', 'GET', '/internal/v3/quotes/{id}/retained'),
    'quote.commit.v3': ('pricing', 'POST', '/internal/v3/quotes/{id}/commit'),
    'payment.notice.v3': ('orders', 'POST', '/internal/v3/payment-notices'),
    'auction.compete.v2': ('auction', 'private', 'serialized-admission'),
}
PREREQUISITES = ('E04', 'A10', 'E08', 'O11', 'S12', 'M08', 'M09', 'E06')


def requirements():
    """Stable lookup keys; every release check must have its own result."""
    rows = {}
    for journey in JOURNEYS:
        for locale in ('en', 'ar'):
            for case in CASES:
                rows[f'journey/{journey}/{locale}/{case}'] = 'connected'
    for domain in DOMAINS:
        for check in ('production-build', 'complete-suite', 'dependency', 'vulnerability'):
            rows[f'domain/{domain}/{check}'] = 'separate-machine'
    for locale in ('en', 'ar'):
        for theme in ('light', 'dark'):
            for viewport in ('desktop', '390x844'):
                for check in ('keyboard', 'geometry', 'accessibility', 'private-retention',
                              'first-frame', 'speed', 'screenshots'):
                    rows[f'view/{locale}/{theme}/{viewport}/{check}'] = 'separate-machine'
    for check in ('receipt-reconciliation', 'load', 'version-rollback-restore',
                  'physical-phone', 'feature-64-coverage'):
        rows[f'release/{check}'] = 'separate-machine'
    for owner in OWNERS:
        rows[f'explanation/{owner}'] = 'owner-rehearsal'
    return rows


def manifest():
    return {
        'schema_version': VERSION,
        'mode': 'preparation-only',
        'operations': {key: dict(zip(('provider', 'method', 'path'), value))
                       for key, value in OPERATIONS.items()},
        'prerequisites': list(PREREQUISITES),
        'results': [{'check_id': key, 'state': 'deferred', 'kind': kind,
                     'reason': 'Current provider and cleared execution proof required.'}
                    for key, kind in requirements().items()],
    }


def validate_binding(value):
    required = ('operation_id', 'subject_id', 'watch_id', 'actor_id',
                'organization_id', 'retained_quote_id', 'policy_revision')
    fields = json.loads((ROOT / 'contract.schema.json').read_text())
    if set(value) != set(fields['required']):
        raise ValueError('binding fields')
    if value.get('schema_version') != VERSION:
        raise ValueError('schema_version')
    for key in required:
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(key)
    for key in ('expected_revision', 'revision'):
        if type(value.get(key)) is not int or value[key] < 1:
            raise ValueError(key)
    if value.get('state') not in ('accepted', 'denied', 'stale', 'pending'):
        raise ValueError('state')
    if value['state'] == 'pending' and not all(value.get(key) for key in (
            'pending_reason', 'next_actor', 'next_review_at')):
        raise ValueError('pending recovery')
    for key in ('pending_reason', 'next_actor', 'next_review_at'):
        if value[key] is not None and not isinstance(value[key], str):
            raise ValueError(key)
    if value['next_review_at'] is not None:
        instant = datetime.fromisoformat(value['next_review_at'].replace('Z', '+00:00'))
        if instant.utcoffset() is None or instant.utcoffset().total_seconds() != 0:
            raise ValueError('UTC required')
    return value


def reconcile(original, response):
    """An uncertain retry retains the original reference and scope."""
    validate_binding(original)
    validate_binding(response)
    for key in ('operation_id', 'subject_id', 'watch_id', 'actor_id',
                'organization_id', 'expected_revision', 'retained_quote_id',
                'policy_revision'):
        if original[key] != response[key]:
            raise ValueError('conflicting receipt')
    if original['state'] in ('accepted', 'denied', 'stale') and (
            response['state'] != original['state'] or response['revision'] != original['revision']):
        raise ValueError('conflicting terminal receipt')
    if response['revision'] < original['revision']:
        raise ValueError('stale receipt')
    return response['state']


def load_summary(durations_ms, errors):
    if not durations_ms or len(durations_ms) > 100000:
        raise ValueError('bounded nonempty sample required')
    if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0
           for x in durations_ms):
        raise ValueError('invalid duration')
    if type(errors) is not int or not 0 <= errors <= len(durations_ms):
        raise ValueError('invalid errors')
    ordered = sorted(durations_ms)
    return {'samples': len(ordered), 'p95_ms': ordered[math.ceil(.95 * len(ordered)) - 1],
            'errors': errors, 'error_rate': errors / len(ordered)}


def evaluate(record):
    """Reject incomplete or fixture-only certification; never run a command."""
    expected = requirements()
    problems = []
    results = record.get('results', [])
    if record.get('schema_version') != VERSION:
        problems.append('schema version missing or unsupported')
    if record.get('blocking_defects') != []:
        problems.append('S0/S1 status missing or unresolved')
    clearance = record.get('clearance', {})
    if not (clearance.get('explicit') is True and clearance.get('separate_machine') is True
            and clearance.get('reference')):
        problems.append('separate release clearance required')
    if not isinstance(record.get('build_id'), str) or not record['build_id']:
        problems.append('named build required')
    if not isinstance(record.get('source_revision'), str) or not record['source_revision']:
        problems.append('source revision required')
    if set(record.get('prerequisites', [])) != set(PREREQUISITES):
        problems.append('connected prerequisites incomplete')
    seen = set()
    explanation_owners = set()
    for row in results:
        key = row.get('check_id')
        if key not in expected or key in seen:
            problems.append('unknown or duplicate check')
            continue
        seen.add(key)
        if row.get('state') != 'passed':
            problems.append(f'{key}: {row.get("state", "missing")}')
            continue
        proof = row.get('proof', {})
        if not (proof.get('source') == 'current-provider' and proof.get('build_id')
                and proof.get('build_id') == record.get('build_id')
                and proof.get('source_revision') == record.get('source_revision')
                and proof.get('synthetic') is True and proof.get('runner')
                and proof.get('repeated_by') and proof['runner'] != proof['repeated_by']
                and proof.get('repeat_build_id') == proof['build_id']
                and proof.get('artifact_ref') and proof.get('command')
                and proof.get('exit_code') == 0
                and type(proof.get('exit_code')) is int):
            problems.append(f'{key}: current repeated proof required')
        if key.startswith('explanation/'):
            owner = proof.get('owner')
            if not isinstance(owner, str) or not owner or owner in explanation_owners:
                problems.append(f'{key}: distinct owner required')
            explanation_owners.add(owner)
        if key == 'release/feature-64-coverage':
            features = proof.get('features', [])
            if len(features) != 64 or len(set(features)) != 64:
                problems.append('64 distinct feature journeys required')
        if '/390x844/' in key and (proof.get('inner_width') != 390
                                    or proof.get('inner_height') != 844):
            problems.append(f'{key}: actual viewport required')
        if key == 'release/load':
            try:
                summary = load_summary(proof['durations_ms'], proof['errors'])
                if (not proof.get('dataset') or not proof.get('connection')
                        or type(proof.get('p95_limit_ms')) not in (int, float)
                        or not math.isfinite(proof['p95_limit_ms'])
                        or proof['p95_limit_ms'] < 0
                        or summary['p95_ms'] > proof['p95_limit_ms']
                        or summary['errors'] != 0):
                    raise ValueError('load target')
            except (KeyError, TypeError, ValueError):
                problems.append('release/load: measured dataset and passing target required')
    for key in expected.keys() - seen:
        problems.append(f'{key}: missing')
    return {'schema_version': VERSION, 'accepted': not problems,
            'remaining_proof': sorted(problems),
            'passed': len(expected) if not problems else 0,
            'declared_passed': sum(row.get('state') == 'passed' for row in results),
            'skipped': sum(row.get('state') == 'skipped' for row in results),
            'deferred': sum(row.get('state') == 'deferred' for row in results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', nargs='?', type=Path)
    args = parser.parse_args()
    if args.record is None:
        print(json.dumps(manifest(), indent=2))
        return 0
    if args.record.stat().st_size > 8 * 1024 * 1024:
        parser.error('record exceeds 8 MiB')
    try:
        result = evaluate(json.loads(args.record.read_text()))
    except (ValueError, TypeError, AttributeError):
        parser.error('invalid release record')
    print(json.dumps(result, indent=2))
    return 0 if result['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
