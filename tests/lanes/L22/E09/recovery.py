"""Release preparation contracts. Does not execute release operations."""
import argparse
import hashlib
import re
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
VERSION = 'L22.E09.v1'
DOMAINS = ('identity', 'catalog', 'auction', 'pricing', 'orders',
           'eligibility', 'trust', 'communications', 'service-operations')
SERVICES = (*DOMAINS, 'web')
REHEARSAL_SCENARIOS = (
    'baseline', 'release-build', *('restart/' + service for service in SERVICES),
    'acknowledged-command', 'rollback', 'restore', 'reconciliation',
)
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


REHEARSAL_CHECKS = {
    'release/version-rollback-restore': ('restart/orders', 'rollback', 'restore'),
    'release/receipt-reconciliation': ('baseline', 'restart/orders', 'acknowledged-command',
                                       'rollback', 'restore', 'reconciliation'),
    **{'domain/' + domain + '/production-build': ('release-build', 'restart/' + domain)
       for domain in DOMAINS},
}


def provider_evidence(results, revision, build):
    by_name = {r['scenario_id']: r for r in results}
    record = manifest()
    record.update(source_revision=revision, build_id=build)
    evidence = {}
    for row in record['results']:
        key = row['check_id']
        names = REHEARSAL_CHECKS.get(key, ())
        if key == 'release/receipt-reconciliation':
            candidate_orders = build + ':orders' if build else None
            recovered = by_name.get('acknowledged-command', {})
            if not candidate_orders or not (
                by_name.get('restart/orders', {}).get('artifact')
                == recovered.get('before_artifact') == recovered.get('artifact') == candidate_orders
            ):
                continue
        if names and all(by_name.get(n, {}).get('state') == 'passed' for n in names):
            evidence[key] = list(names)
            row.update(state='passed', proof=dict(source='current-provider', build_id=build,
                       source_revision=revision, synthetic=False, seeded=False,
                       measurements=[by_name[n] for n in names]))
    assessment = evaluate(record)
    return dict(provider_evidence=evidence, remaining_proof=assessment['remaining_proof'],
                certification_accepted=assessment['accepted'])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sha256(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def process_transition(row, service):
    before, after = row.get('before_pid'), row.get('after_pid')
    old_start, new_start = row.get('before_start'), row.get('after_start')
    return (row.get('service') == service and row.get('ready') is True
            and type(before) is int and type(after) is int
            and min(before, after) > 0 and before != after
            and all(isinstance(start, str) and start.isdecimal() for start in (old_start, new_start))
            and old_start != new_start)


def references(row, field):
    values = row.get(field)
    if (not isinstance(values, list) or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)):
        return set()
    return set(values) if len(set(values)) == len(values) else set()


def recovery_measurements(scenarios, candidate):
    restart, rollback, restore, command = (
        scenarios[name] for name in ('restart/orders', 'rollback', 'restore', 'acknowledged-command'))
    prior = restart.get('before_artifact')
    old_code, new_code = restart.get('before_orders_executable'), restart.get('orders_executable')
    if not (isinstance(prior, str) and prior.endswith(':orders') and sha256(prior[:-7])
            and prior != candidate == rollback.get('before_artifact')
            and prior == rollback.get('artifact') == rollback.get('previous_artifact')
            and sha256(old_code) and sha256(new_code)
            and old_code == rollback.get('orders_executable')
            and new_code == rollback.get('before_orders_executable')
            and process_transition(rollback, 'orders')
            and rollback.get('migrations_reversed') is False
            and rollback.get('current_authority_verified') is True
            and candidate == command.get('before_artifact') == command.get('artifact')
            and process_transition(command, 'orders')
            and restart['after_pid'] == command['before_pid']
            and restart['after_start'] == command['before_start']
            and command['after_pid'] == rollback['before_pid']
            and command['after_start'] == rollback['before_start']
            and command.get('same_reference') is True
            and command.get('response_discarded') is True):
        return False
    domains = restore.get('restored_domains')
    if not (restore.get('backup_provider') == 'E04' and sha256(restore.get('backup_reference'))
            and restore.get('isolated') is True and restore.get('postgres_major') == 17
            and isinstance(domains, list) and sorted(DOMAINS) == sorted(
                domain for domain in domains if isinstance(domain, str))
            and len(domains) == len(DOMAINS)
            and restore.get('lost_acknowledged_operations') == []
            and restore.get('current_deletions_applied') is True
            and restore.get('current_revocations_applied') is True):
        return False
    baseline = scenarios['baseline']
    recovered = references(command, 'recovered_callback_ids')
    original = references(baseline, 'acknowledged_baseline_ids')
    if not (len(recovered) == 1 and recovered == references(command, 'acknowledged_callback_ids')
            and original and original <= references(baseline, 'product_operation_ids')
            and not original & recovered):
        return False
    for field, required in (
        ('product_operation_ids', (original, recovered)),
        ('custody_receipt_ids', (references(baseline, 'custody_receipt_ids'),
                                references(command, 'custody_receipt_ids'))),
        ('custody_operation_ids', (references(baseline, 'custody_operation_ids'),
                                  references(command, 'custody_operation_ids'))),
    ):
        first, second = required
        if not (first and second and not first & second and second <= references(command, field)
                and all(first | second <= references(row, field)
                        for row in (rollback, restore, scenarios['reconciliation']))):
            return False
    return True


def verified_rehearsal(run, key):
    build_id = run['build_id']
    summary = run['measurements']
    if not (isinstance(build_id, str) and re.fullmatch(r'[0-9a-f]{64}', build_id)
            and summary.get('schema_version') == 'L22.E09.driver.v1'
            and summary.get('state') == 'passed'
            and digest(summary) == run['artifact_sha256']
            and all(summary.get(field) == run[field]
                    for field in ('build_id', 'source_revision', 'run_id'))):
        return False
    rows = summary.get('results')
    if not isinstance(rows, list) or not all(isinstance(row, dict)
            and isinstance(row.get('scenario_id'), str)
            and row.get('state') == 'passed' for row in rows):
        return False
    scenarios = {row['scenario_id']: row for row in rows}
    if (len(scenarios) != len(rows) or set(scenarios) != set(REHEARSAL_SCENARIOS)
            or any(row.get('source_revision') != run['source_revision'] for row in rows)):
        return False
    if scenarios['release-build'].get('build_id') != build_id:
        return False
    for service in SERVICES:
        restart = scenarios['restart/' + service]
        if (restart.get('artifact') != f'{build_id}:{service}'
                or not process_transition(restart, service)):
            return False
    return not key.startswith('release/') or recovery_measurements(scenarios, f'{build_id}:orders')


def verified_measurements(key, run):
    """Require measurements and a supporting artifact for each reviewed run."""
    measured = run['measurements']
    if digest(measured) != run['artifact_sha256'] or not sha256(measured.get('evidence_sha256')):
        return False
    parts = key.split('/')
    category, check = parts[0], parts[-1]

    def nonempty(field):
        value = measured.get(field)
        return isinstance(value, str) and bool(value.strip())

    def count(field, minimum=0):
        value = measured.get(field)
        return type(value) is int and value >= minimum

    if category == 'domain':
        if measured.get('domain') != parts[1] or not nonempty('command'):
            return False
        if type(measured.get('exit_code')) is not int or measured['exit_code'] != 0:
            return False
        if check == 'complete-suite':
            return (measured.get('scope') == 'complete' and count('passed', 1)
                    and all(type(measured.get(field)) is int and measured[field] == 0
                            for field in ('failed', 'skipped', 'errors')))
        if not (count('components', 1) and sha256(measured.get('inventory_sha256'))):
            return False
        if check == 'dependency':
            return measured.get('inventory_complete') is True and measured.get('unresolved') == []
        return (measured.get('scan_complete') is True and nonempty('advisory_revision')
                and measured.get('unresolved') == [])
    if category == 'journey':
        return (measured.get('journey') == parts[1] and measured.get('locale') == parts[2]
                and measured.get('case') == check and bool(references(measured, 'product_operation_ids'))
                and nonempty('expected_outcome') and measured.get('outcome') == measured['expected_outcome'])
    if category == 'view':
        observations = {
            'keyboard': 'keyboard_paths', 'geometry': 'geometry_samples',
            'accessibility': 'accessibility_checks', 'private-retention': 'access_change_cases',
            'first-frame': 'first_frame_samples', 'speed': 'page_read_keys',
            'screenshots': 'capture_ids',
        }
        return (all(measured.get(field) == value for field, value in
                    zip(('locale', 'theme', 'viewport', 'check'), parts[1:]))
                and bool(references(measured, observations[check]))
                and (parts[3] != '390x844' or
                     (measured.get('inner_width'), measured.get('inner_height')) == (390, 844))
                and count('failures') and measured['failures'] == 0)
    if category == 'explanation':
        return measured.get('responsibility') == check and nonempty('finding')
    if check == 'physical-phone':
        return (measured.get('physical_device') is True and nonempty('device_model')
                and {'en', 'ar'} == references(measured, 'locales')
                and bool(references(measured, 'journey_ids')))
    if check == 'feature-64-coverage':
        features = measured.get('features')
        return (isinstance(features, dict) and set(features) == {f'F{i}' for i in range(1, 65)}
                and all(sha256(value) for value in features.values()))
    if check == 'load':
        return passing_load(measured)
    return False


def passing_load(measured):
    try:
        summary = load_summary(measured['durations_ms'], measured['errors'])
        limit = measured['p95_limit_ms']
        return (all(isinstance(measured.get(field), str) and measured[field].strip()
                    for field in ('dataset', 'connection'))
                and type(limit) in (int, float) and math.isfinite(limit)
                and 0 <= summary['p95_ms'] <= limit and summary['errors'] == 0)
    except (KeyError, TypeError, ValueError):
        return False


def verified_runs(runs, key, record, proof):
    if not isinstance(runs, list) or len(runs) != 2:
        return False
    build_ids = (proof.get('build_id'), proof.get('repeat_build_id'))
    people = (proof.get('runner'), proof.get('repeated_by'))
    if build_ids[0] != build_ids[1]:
        return False
    for run, person, build_id, mode in zip(runs, people, build_ids, ('built', 'reused')):
        if not (isinstance(run, dict) and run.get('check_id') == key
                and run.get('build_id') == build_id
                and run.get('source_revision') == record['source_revision']
                and isinstance(person, str) and person.strip() and run.get('person') == person
                and run.get('state') == 'passed'
                and run.get('synthetic') is False and run.get('seeded') is False
                and isinstance(run.get('run_id'), str) and run['run_id'].strip()
                and re.fullmatch(r'[0-9a-f]{64}', str(run.get('artifact_sha256', '')))
                and isinstance(run.get('measurements'), dict) and run['measurements']):
            return False
        if key in REHEARSAL_CHECKS:
            if not verified_rehearsal(run, key):
                return False
            build = next(row for row in run['measurements']['results']
                         if row['scenario_id'] == 'release-build')
            if build.get('archive_mode') != mode:
                return False
        elif not verified_measurements(key, run):
            return False
    first, repeat = runs
    if key not in REHEARSAL_CHECKS and (
            first['measurements']['evidence_sha256'] == repeat['measurements']['evidence_sha256']):
        return False
    return (first['run_id'] != repeat['run_id']
            and first['artifact_sha256'] != repeat['artifact_sha256']
            and first['person'].strip().casefold() != repeat['person'].strip().casefold()
            and first['measurements'] == proof.get('measurements')
            and first['artifact_sha256'] == proof.get('artifact_ref'))


def evaluate(record, *, reviewed=None):
    """Reject incomplete or fixture-only certification; never run a command."""
    expected = requirements()
    problems = []
    if not (isinstance(reviewed, dict)
            and isinstance(reviewed.get('reviewed_by'), str) and reviewed['reviewed_by'].strip()
            and reviewed.get('schema_version') == 1
            and reviewed.get('record_sha256') == digest(record)
            and isinstance(reviewed.get('checks'), dict)):
        reviewed = {}
        problems.append('independently reviewed provider evidence required')
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
        review = reviewed.get('checks', {}).get(key, {})
        if not (proof.get('source') == 'current-provider' and proof.get('build_id')
                and proof.get('build_id') == record.get('build_id')
                and proof.get('source_revision') == record.get('source_revision')
                and proof.get('synthetic') is False and proof.get('seeded') is False and proof.get('runner')
                and proof.get('repeated_by') and proof['runner'] != proof['repeated_by']
                and isinstance(proof.get('repeat_build_id'), str) and proof['repeat_build_id'].strip()
                and proof.get('artifact_ref') and proof.get('command')
                and proof.get('exit_code') == 0
                and type(proof.get('exit_code')) is int
                and verified_runs(review.get('runs'), key, record, proof)):
            problems.append(f'{key}: current repeated proof required')
        if key.startswith('explanation/'):
            owner = proof.get('owner')
            name = ' '.join(owner.split()).casefold() if isinstance(owner, str) else ''
            explanation = review.get('explanation')
            if (not name or name in explanation_owners or name in OWNERS or name in expected
                    or not isinstance(explanation, dict) or explanation.get('person') != owner
                    or not isinstance(explanation.get('text'), str)
                    or not explanation['text'].strip()):
                problems.append(f'{key}: distinct named owner explanation required')
            else:
                explanation_owners.add(name)
        if key == 'release/feature-64-coverage':
            features = proof.get('features', [])
            if len(features) != 64 or len(set(features)) != 64:
                problems.append('64 distinct feature journeys required')
        if '/390x844/' in key and (proof.get('inner_width') != 390
                                    or proof.get('inner_height') != 844):
            problems.append(f'{key}: actual viewport required')
        if key == 'release/load' and not passing_load(proof):
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
    parser.add_argument('--reviewed-evidence', type=Path)
    args = parser.parse_args()
    if args.record is None:
        print(json.dumps(manifest(), indent=2))
        return 0
    if args.record.stat().st_size > 8 * 1024 * 1024:
        parser.error('record exceeds 8 MiB')
    try:
        reviewed = None
        if args.reviewed_evidence:
            if args.reviewed_evidence.stat().st_size > 8 * 1024 * 1024:
                parser.error('reviewed evidence exceeds 8 MiB')
            reviewed = json.loads(args.reviewed_evidence.read_text())
        result = evaluate(json.loads(args.record.read_text()), reviewed=reviewed)
    except (ValueError, TypeError, AttributeError, KeyError, OSError):
        parser.error('invalid release record')
    print(json.dumps(result, indent=2))
    return 0 if result['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
