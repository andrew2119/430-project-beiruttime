import copy
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import recovery


def reviewed_measurement(key, index):
    parts = key.split('/')
    category, check = parts[0], parts[-1]
    artifact = recovery.digest(['test-artifact', key, index])
    measured = {'evidence_sha256': artifact}
    if category == 'domain':
        measured.update(domain=parts[1], command='test-domain-check', exit_code=0)
        if check == 'complete-suite':
            measured.update(scope='complete', passed=5, failed=0, skipped=0, errors=0)
        else:
            measured.update(components=5, inventory_sha256=artifact, unresolved=[])
            if check == 'dependency':
                measured.update(inventory_complete=True)
            else:
                measured.update(scan_complete=True, advisory_revision='test-advisories')
    elif category == 'journey':
        measured.update(journey=parts[1], locale=parts[2], case=check,
                        product_operation_ids=['test-operation'],
                        expected_outcome='test-outcome', outcome='test-outcome')
    elif category == 'view':
        measured.update(locale=parts[1], theme=parts[2], viewport=parts[3], check=check,
                        inner_width=390, inner_height=844, failures=0)
        measured.update({field: ['test-observation'] for field in (
            'keyboard_paths', 'geometry_samples', 'accessibility_checks',
            'access_change_cases', 'first_frame_samples', 'page_read_keys', 'capture_ids')})
    elif category == 'explanation':
        measured.update(responsibility=check, finding='test-measured-finding')
    elif check == 'physical-phone':
        measured.update(physical_device=True, device_model='test-device',
                        locales=['en', 'ar'], journey_ids=['test-journey'])
    elif check == 'feature-64-coverage':
        measured.update(features={f'F{i}': recovery.digest(['test-feature', i])
                                  for i in range(1, 65)})
    elif check == 'load':
        measured.update(durations_ms=[10], errors=0, p95_limit_ms=20,
                        dataset='test-dataset', connection='test-connection')
    return measured


class ReleasePreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / 'fixtures.json').read_text())

    def complete_record(self):
        record = recovery.manifest()
        record.update(blocking_defects=[], build_id='a' * 64,
                      source_revision='source-001',
                      clearance={'explicit': True, 'separate_machine': True,
                                 'reference': 'clearance-001'})
        for row in record['results']:
            row['state'] = 'passed'
            row['proof'] = {
                'source': 'current-provider', 'synthetic': False, 'seeded': False,
                'source_revision': 'source-001', 'build_id': 'a' * 64,
                'runner': 'person-001', 'repeated_by': 'person-002',
                'repeat_build_id': 'a' * 64, 'artifact_ref': 'artifact-001',
                'command': 'recorded-module-check', 'exit_code': 0,
                'inner_width': 390, 'inner_height': 844,
                'durations_ms': [10] * 100, 'errors': 0,
                'dataset': 'synthetic-100', 'connection': 'isolated', 'p95_limit_ms': 20,
                'owner': row['check_id'],
                'features': [f'feature-{i:02}' for i in range(64)],
            }
        return record

    def test_deferred_manifest_never_passes(self):
        result = recovery.evaluate(recovery.manifest())
        self.assertFalse(result['accepted'])
        self.assertEqual(result['deferred'], len(recovery.requirements()))
        self.assertEqual(result['passed'], 0)

    def test_preparation_declarations_cannot_certify(self):
        result = recovery.evaluate(self.complete_record())
        self.assertFalse(result['accepted'])
        self.assertIn('independently reviewed provider evidence required', result['remaining_proof'])

    def test_review_binds_each_run_and_named_owner_to_the_exact_record(self):
        record = self.complete_record()
        reviewed = dict(schema_version=1, reviewed_by='Test Reviewer', checks={})
        for row in record['results']:
            key, proof = row['check_id'], row['proof']
            runs = [
                dict(check_id=key, state='passed', synthetic=False, seeded=False,
                     person=person, run_id='test-run-' + str(index),
                     build_id=record['build_id'], source_revision=record['source_revision'],
                     measurements=reviewed_measurement(key, index))
                for index, person in enumerate(('person-001', 'person-002'), 1)
            ]
            if key in recovery.REHEARSAL_CHECKS:
                for run, mode in zip(runs, ('built', 'reused')):
                    build = run['build_id']
                    rows = []
                    prior = 'e' * 64 + ':orders'
                    old_code = 'd' * 64
                    new_code = old_code if key == 'release/version-rollback-restore' else 'f' * 64
                    baseline = dict(product_operation_ids=['test-baseline'],
                                    custody_receipt_ids=['test-baseline-receipt'],
                                    custody_operation_ids=['test-baseline-intake'])
                    command = dict(product_operation_ids=['test-callback'],
                                   custody_receipt_ids=['test-callback-receipt'],
                                   custody_operation_ids=['test-callback-intake'])
                    retained = {field: baseline[field] + command[field] for field in baseline}

                    def transition(service, pid):
                        return dict(service=service, ready=True, before_pid=pid, after_pid=pid + 1,
                                    before_start=str(pid * 2), after_start=str((pid + 1) * 2))

                    for name in recovery.REHEARSAL_SCENARIOS:
                        row = dict(scenario_id=name, state='passed', source_revision=run['source_revision'])
                        if name.startswith('restart/'):
                            service = name.split('/', 1)[1]
                            row.update(transition(service, 100), artifact=build + ':' + service)
                        if name == 'restart/orders':
                            row.update(before_artifact=prior, before_orders_executable=old_code,
                                       orders_executable=new_code)
                        if name == 'release-build':
                            row.update(build_id=build, archive_mode=mode)
                        if name == 'baseline':
                            row.update(baseline, acknowledged_baseline_ids=['test-baseline'])
                        if name == 'acknowledged-command':
                            row.update(transition('orders', 101), **command,
                                       before_artifact=build + ':orders', artifact=build + ':orders',
                                       same_reference=True, response_discarded=True,
                                       recovered_callback_ids=['test-callback'],
                                       acknowledged_callback_ids=['test-callback'])
                        if name == 'rollback':
                            row.update(transition('orders', 102), **retained,
                                       before_artifact=build + ':orders', artifact=prior,
                                       previous_artifact=prior, before_orders_executable=new_code,
                                       orders_executable=old_code, migrations_reversed=False,
                                       current_authority_verified=True)
                        if name == 'restore':
                            row.update(retained, backup_provider='E04', backup_reference='1' * 64,
                                       isolated=True, postgres_major=17, restored_domains=list(recovery.DOMAINS),
                                       lost_acknowledged_operations=[], current_deletions_applied=True,
                                       current_revocations_applied=True)
                        if name == 'reconciliation':
                            row.update(retained)
                        rows.append(row)
                    run['measurements'] = dict(
                        schema_version='L22.E09.driver.v1', source_revision=run['source_revision'],
                        build_id=build, run_id=run['run_id'], results=rows, state='passed',
                    )
                    run['artifact_sha256'] = recovery.digest(run['measurements'])
            else:
                for run in runs:
                    run['artifact_sha256'] = recovery.digest(run['measurements'])
            proof.update(artifact_ref=runs[0]['artifact_sha256'], measurements=runs[0]['measurements'])
            reviewed['checks'][key] = {'runs': runs}
            if key.startswith('explanation/'):
                proof['owner'] = 'Test Person ' + key.split('/')[-1]
                reviewed['checks'][key]['explanation'] = {
                    'person': proof['owner'], 'text': 'Measured review of ' + key}

        reviewed['record_sha256'] = recovery.digest(record)
        def evaluate(candidate=record):
            return recovery.evaluate(candidate, reviewed=reviewed)

        for row in record['results']:
            key = row['check_id']
            assert recovery.verified_runs(reviewed['checks'][key]['runs'], key, record, row['proof'])
        for key in recovery.requirements().keys() - recovery.REHEARSAL_CHECKS.keys():
            for index in range(2):
                with self.subTest(check=key, run=index):
                    runs = copy.deepcopy(reviewed['checks'][key]['runs'])
                    runs[index]['measurements'] = {'seconds': 2}
                    runs[index]['artifact_sha256'] = recovery.digest(runs[index]['measurements'])
                    proof = next(row['proof'] for row in record['results'] if row['check_id'] == key)
                    self.assertFalse(recovery.verified_runs(runs, key, record, dict(
                        proof, measurements=runs[0]['measurements'],
                        artifact_ref=runs[0]['artifact_sha256'])))
        self.assertTrue(evaluate()['accepted'])

        for key in recovery.REHEARSAL_CHECKS:
            proof = next(row['proof'] for row in record['results'] if row['check_id'] == key)
            for index in range(2):
                for missing in recovery.REHEARSAL_SCENARIOS:
                    with self.subTest(check=key, run=index, missing=missing):
                        runs = copy.deepcopy(reviewed['checks'][key]['runs'])
                        run = runs[index]
                        summary = run['measurements']
                        summary['results'] = [row for row in summary['results']
                                              if row['scenario_id'] != missing]
                        run['artifact_sha256'] = recovery.digest(summary)
                        primary = runs[0]
                        assert not recovery.verified_runs(runs, key, record, dict(
                            proof, measurements=primary['measurements'],
                            artifact_ref=primary['artifact_sha256']))
            for outcome, failure in (
                    ('failed', None), ('failed', 'cleanup'),
                    ('passed', 'cleanup'), ('passed', 'interruption')):
                runs = copy.deepcopy(reviewed['checks'][key]['runs'])
                for index, run in enumerate(runs):
                    summary = run['measurements']
                    summary['state'] = outcome
                    if failure:
                        summary['results'].append(dict(scenario_id=failure, state='failed'))
                    run['artifact_sha256'] = recovery.digest(summary)
                    primary = runs[0]
                    assert not recovery.verified_runs(runs, key, record, dict(
                        proof, measurements=primary['measurements'],
                        artifact_ref=primary['artifact_sha256']))
                    runs[index] = copy.deepcopy(reviewed['checks'][key]['runs'][index])
        for invalid in ({}, dict(reviewed, reviewed_by=' '), dict(reviewed, checks={})):
            assert not recovery.evaluate(record, reviewed=invalid)['accepted']
        changed = copy.deepcopy(record)
        changed['results'][0]['proof']['measurements']['seconds'] = 3
        assert not evaluate(changed)['accepted']

        for key in recovery.REHEARSAL_CHECKS:
            proof = next(row['proof'] for row in record['results'] if row['check_id'] == key)
            runs = copy.deepcopy(reviewed['checks'][key]['runs'])
            repeat = runs[1]
            old_build, new_build = repeat['build_id'], 'b' * 64
            alternate = json.dumps(repeat['measurements']).replace(old_build, new_build)
            repeat.update(build_id=new_build, measurements=json.loads(alternate))
            repeat['artifact_sha256'] = recovery.digest(repeat['measurements'])
            assert recovery.verified_rehearsal(repeat, key)
            assert not recovery.verified_runs(
                runs, key, record, dict(proof, repeat_build_id=new_build))

        key = 'domain/orders/production-build'
        proof = next(row['proof'] for row in record['results'] if row['check_id'] == key)
        runs = copy.deepcopy(reviewed['checks'][key]['runs'])
        repeat = runs[1]
        build = next(row for row in repeat['measurements']['results']
                     if row['scenario_id'] == 'release-build')
        build['archive_mode'] = 'built'
        repeat['artifact_sha256'] = recovery.digest(repeat['measurements'])
        assert not recovery.verified_runs(runs, key, record, proof)

        for key in ('release/version-rollback-restore', 'release/receipt-reconciliation'):
            repeat = reviewed['checks'][key]['runs'][1]
            scenarios = {row['scenario_id']: row for row in repeat['measurements']['results']}
            for name, field in (
                    ('acknowledged-command', 'recovered_callback_ids'),
                    ('acknowledged-command', 'custody_operation_ids'),
                    ('rollback', 'previous_artifact'),
                    ('restore', 'backup_reference'),
                    ('restore', 'restored_domains'),
                    ('restore', 'lost_acknowledged_operations'),
                    ('restore', 'current_revocations_applied'),
                    ('reconciliation', 'product_operation_ids')):
                row = scenarios[name]
                value = row.pop(field)
                repeat['artifact_sha256'] = recovery.digest(repeat['measurements'])
                result = evaluate()
                assert f'{key}: current repeated proof required' in result['remaining_proof']
                row[field] = value
            repeat['artifact_sha256'] = recovery.digest(repeat['measurements'])

        key = 'release/receipt-reconciliation'
        repeat = reviewed['checks'][key]['runs'][1]
        restart = next(row for row in repeat['measurements']['results']
                       if row['scenario_id'] == 'restart/orders')
        original = restart['artifact']
        restart['artifact'] = 'b' * 64 + ':orders'
        repeat['artifact_sha256'] = recovery.digest(repeat['measurements'])
        result = evaluate()
        assert f'{key}: current repeated proof required' in result['remaining_proof']
        restart['artifact'] = original
        repeat['artifact_sha256'] = recovery.digest(repeat['measurements'])
        for field, value in [('build_id', 'c' * 64), ('source_revision', 'test-other-revision'),
                             ('artifact_sha256', 'd' * 64)]:
            original_value = repeat[field]
            repeat[field] = value
            result = evaluate()
            assert f'{key}: current repeated proof required' in result['remaining_proof']
            repeat[field] = original_value

        key = record['results'][0]['check_id']
        repeat = reviewed['checks'][key]['runs'][1]
        repeat['run_id'] = reviewed['checks'][key]['runs'][0]['run_id']
        result = evaluate()
        assert f'{key}: current repeated proof required' in result['remaining_proof']

        key = 'explanation/' + recovery.OWNERS[0]
        reviewed['checks'][key]['explanation']['text'] = ''
        result = evaluate()
        assert f'{key}: distinct named owner explanation required' in result['remaining_proof']

    def test_release_vetoes(self):
        mutations = [
            lambda r: r.update(blocking_defects=['S0: lost acknowledged payment']),
            lambda r: r.pop('blocking_defects'),
            lambda r: r.update(clearance={}),
            lambda r: r.update(prerequisites=[]),
            lambda r: r.pop('source_revision'),
            lambda r: r['results'].pop(),
            lambda r: r['results'].append(copy.deepcopy(r['results'][0])),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                record = self.complete_record()
                mutate(record)
                self.assertFalse(recovery.evaluate(record)['accepted'])

    def test_proof_vetoes(self):
        for patch in ({'source': 'fixture'}, {'source': 'screenshot'},
                      {'repeated_by': 'person-001'}, {'repeat_build_id': 'old'},
                      {'build_id': 'old'}, {'source_revision': 'old'},
                      {'synthetic': True}, {'seeded': True}, {'exit_code': 1}, {'exit_code': False},
                      {'artifact_ref': ''}, {'command': ''}):
            record = self.complete_record()
            record['results'][0]['proof'].update(patch)
            with self.subTest(patch=patch):
                self.assertFalse(recovery.evaluate(record)['accepted'])

    def test_skip_pending_deferred_and_unknown_states_remain_owed(self):
        for state in ('skipped', 'pending', 'deferred', 'unknown'):
            record = self.complete_record()
            record['results'][0].update(state=state, reason='provider unavailable')
            self.assertFalse(recovery.evaluate(record)['accepted'])

    def test_actual_phone_viewport_required(self):
        record = self.complete_record()
        row = next(r for r in record['results'] if '/390x844/' in r['check_id'])
        row['proof']['inner_width'] = 391
        self.assertFalse(recovery.evaluate(record)['accepted'])

    def test_five_distinct_owners_and_64_features(self):
        for key, value in (('explanation/', {'owner': ''}),
                           ('release/feature-64-coverage', {'features': ['feature-00'] * 64})):
            record = self.complete_record()
            next(r for r in record['results'] if r['check_id'].startswith(key))['proof'].update(value)
            self.assertFalse(recovery.evaluate(record)['accepted'])

    def test_fixtures_and_stable_receipt_recovery(self):
        original = self.fixture['binding']
        for case, patch in self.fixture['responses'].items():
            with self.subTest(case=case):
                response = {**original, **patch}
                self.assertEqual(recovery.reconcile(original, response), patch['state'])
                self.assertEqual(recovery.reconcile(original, response), patch['state'])

    def test_terminal_receipt_cannot_change_on_retry(self):
        original = {**self.fixture['binding'], 'state': 'accepted'}
        self.assertEqual(recovery.reconcile(original, original), 'accepted')
        for patch in ({'state': 'denied'}, {'revision': 5}):
            with self.assertRaises(ValueError):
                recovery.reconcile(original, {**original, **patch})

    def test_scope_and_revision_conflicts_rejected(self):
        original = self.fixture['binding']
        for key in ('operation_id', 'subject_id', 'watch_id', 'actor_id',
                    'organization_id', 'retained_quote_id', 'policy_revision',
                    'expected_revision', 'revision'):
            response = dict(original)
            response[key] = 2 if type(response[key]) is int else 'different'
            with self.subTest(key=key), self.assertRaises(ValueError):
                recovery.reconcile(original, response)

    def test_binding_schema_and_pending_recovery(self):
        original = self.fixture['binding']
        schema = json.loads((recovery.ROOT / 'contract.schema.json').read_text())
        self.assertEqual(set(original), set(schema['required']))
        for patch in ({'expected_revision': True}, {'revision': 0},
                      {'next_actor': None}, {'next_review_at': '2026-11-17T10:00:00'},
                      {'private_evidence': 'forbidden'}, {'state': 'paid'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                recovery.validate_binding({**original, **patch})

    def test_fixture_economics_are_not_connected_proof(self):
        value = self.fixture['economics']
        self.assertTrue(self.fixture['synthetic'])
        self.assertFalse(self.fixture['connected_proof'])
        self.assertTrue(all(type(v) is int for k, v in value.items() if k != 'currency'))
        self.assertEqual(value['watch_buyer_total_minor'], 515000)
        self.assertEqual(value['seller_commission_minor'], 25000)
        self.assertEqual(value['job_total_minor'] - value['job_business_fee_minor'],
                         value['job_business_net_minor'])
        self.assertEqual(value['job_refund_max_minor'], value['job_total_minor'])

    def test_clock_fixture_strict_boundary(self):
        clock = {k: datetime.fromisoformat(v.replace('Z', '+00:00'))
                 for k, v in self.fixture['payment_clock'].items()}
        self.assertEqual(clock['card_deadline'] - clock['notified_at'], timedelta(hours=24))
        self.assertEqual(clock['other_deadline'] - clock['notified_at'], timedelta(hours=48))
        self.assertLess(clock['attempt_before'], clock['card_deadline'])
        self.assertEqual(clock['attempt_equal'], clock['card_deadline'])
        self.assertGreater(clock['attempt_after'], clock['card_deadline'])

    def test_load_bounded_nearest_rank(self):
        self.assertEqual(recovery.load_summary(list(range(1, 101)), 2),
                         {'samples': 100, 'p95_ms': 95, 'errors': 2, 'error_rate': .02})
        for durations, errors in (([], 0), ([True], 0), ([float('inf')], 0),
                                  ([1], True), ([1], 2), ([-1], 0), ([1] * 100001, 0)):
            with self.subTest(errors=errors), self.assertRaises(ValueError):
                recovery.load_summary(durations, errors)
        record = self.complete_record()
        row = next(r for r in record['results'] if r['check_id'] == 'release/load')
        row['proof']['errors'] = 1
        self.assertFalse(recovery.evaluate(record)['accepted'])

    def test_matrix_is_deterministic_and_covers_nine_domains(self):
        self.assertEqual(recovery.manifest(), recovery.manifest())
        keys = recovery.requirements()
        for domain in recovery.DOMAINS:
            self.assertIn(f'domain/{domain}/production-build', keys)
        self.assertEqual(len(recovery.DOMAINS), 9)
        self.assertEqual(len(recovery.OWNERS), 5)
        self.assertEqual(len(keys), 366)


if __name__ == '__main__':
    unittest.main()


def test_receipt_evidence_requires_the_candidate_orders_transition_and_recovery():
    from recovery import provider_evidence

    check = 'release/receipt-reconciliation'
    artifact = 'test-build:orders'
    restart = dict(scenario_id='restart/orders', state='passed', artifact=artifact)
    recovery = dict(scenario_id='acknowledged-command', state='passed',
                    artifact=artifact, before_artifact=artifact)
    reads = [dict(scenario_id=name, state='passed') for name in ('baseline', 'rollback', 'restore', 'reconciliation')]

    def evidence(transition, command, failed=None):
        scenarios = [dict(row, state="failed") if row["scenario_id"] == failed else row
                     for row in reads]
        return provider_evidence([*scenarios, transition, command],
                                 'test-revision', 'test-build')['provider_evidence']

    assert check in evidence(restart, recovery)
    assert check not in evidence(restart, recovery, failed="rollback")
    assert check not in evidence(restart, recovery, failed="restore")
    assert check not in evidence(dict(restart, state='failed'), recovery)
    assert check not in evidence(dict(restart, artifact='test-prior:orders'), recovery)
    assert check not in evidence(restart, dict(recovery, before_artifact='test-prior:orders'))
    assert check not in evidence(restart, dict(recovery, artifact='test-prior:orders'))
