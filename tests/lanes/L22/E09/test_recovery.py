import copy
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import recovery


class ReleasePreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / 'fixtures.json').read_text())

    def complete_record(self):
        record = recovery.manifest()
        record.update(blocking_defects=[], build_id='synthetic-001',
                      source_revision='source-001',
                      clearance={'explicit': True, 'separate_machine': True,
                                 'reference': 'clearance-001'})
        for row in record['results']:
            row['state'] = 'passed'
            row['proof'] = {
                'source': 'current-provider', 'synthetic': True,
                'source_revision': 'source-001', 'build_id': 'synthetic-001',
                'runner': 'person-001', 'repeated_by': 'person-002',
                'repeat_build_id': 'synthetic-001', 'artifact_ref': 'artifact-001',
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

    def test_complete_declarations_meet_record_contract_only(self):
        self.assertTrue(recovery.evaluate(self.complete_record())['accepted'])

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
                      {'synthetic': False}, {'exit_code': 1}, {'exit_code': False},
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
