import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runner


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(runner.PLAN.read_text())

    def test_complete_accounting(self):
        rows = runner.check_plan(self.plan)
        self.assertEqual(len(rows), 291)
        for number in range(1, 65):
            for locale in ('en', 'ar'):
                for theme in ('light', 'dark'):
                    self.assertIn(f'journey_{number:02}_{locale}_{theme}', [r['id'] for r in rows])

    def test_original_crosswalk_rejects_omissions_and_stale_source(self):
        for mutation in ('missing', 'stale', 'discarded_cases'):
            plan = copy.deepcopy(self.plan)
            if mutation == 'missing':
                plan['original_crosswalk']['coverage'].pop()
            elif mutation == 'stale':
                plan['original_crosswalk']['sha256'] = '0' * 64
            else:
                plan['original_crosswalk']['coverage'][0]['cases'] = 'positive_only'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                runner.check_plan(plan)

    def test_plan_mutations(self):
        for mutation in ('missing', 'duplicate', 'ownership', 'lifecycle', 'assertions', 'content'):
            plan = copy.deepcopy(self.plan)
            if mutation == 'missing':
                plan['requirements'].pop()
            elif mutation == 'duplicate':
                plan['requirements'].append(plan['requirements'][0])
            elif mutation == 'content':
                plan['requirements'][-1]['content']['positive'] = 'generic_success'
            else:
                key = {'ownership': 'provider'}.get(mutation, mutation)
                plan['requirements'][0][key] = []
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                runner.check_plan(plan)

    def test_unsafe_success_mutations(self):
        row = copy.deepcopy(self.plan['requirements'][0])
        row.update(entrypoint='tests/provider/scenario.json', source_revision='a' * 40)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / 'result.json'

            record = dict(schema_version=row['contract_version'], requirement=row['id'],
                          provider=row['provider'], scenario=row['scenario'],
                          source_revision=row['source_revision'], entrypoint=row['entrypoint'],
                          origin='http://localhost:3000', run_id='first-run', execution='real_provider',
                          result='passed', fixture_only=False,
                          assertions={a: True for a in row['assertions']},
                          lifecycle={d: 'passed' for d in row['lifecycle']},
                          content=row['content'], artifacts=[])
            outcome = self.outcome(record)
            artifact.write_text(json.dumps(outcome))
            record['artifacts'] = [{'path': 'result.json', 'sha256': runner.digest(artifact)}]
            runner.validate_evidence(row, record, root, record['origin'], record['run_id'])
            mutations = {'source_revision': 'b' * 40, 'execution': 'fixture', 'fixture_only': True,
                         'assertions': {'positive': True}, 'lifecycle': {}, 'result': 'awaiting_payment',
                         'provider': 'E09', 'run_id': 'old-run', 'artifacts': []}
            for key, value in mutations.items():
                changed = copy.deepcopy(record)
                changed[key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    runner.validate_evidence(row, changed, root, record['origin'], record['run_id'])
            artifact.write_text('{"changed":true}')
            with self.assertRaises(ValueError):
                runner.validate_evidence(row, record, root, record['origin'], record['run_id'])

    def outcome(self, record):
        cases = {}
        for kind in ('positive', 'negative', 'recovery'):
            cases[kind] = dict(
                operation_id=kind, retry_operation_id=kind, assertion=record['content'][kind],
                state='denied' if kind == 'negative' else record['content'][kind + '_state'],
                effects=[], settlement_state=('awaiting_payment' if record['requirement'] == 'allocation_fixed_price'
                                  else 'completed'), mutated=False,
                watch_id='watch-1', quality='passed', window_expired=True, hold=False,
                authority=dict(current=True, expected_revision=2, revision=2,
                               actor_id='buyer', reviewer_ids=['assessor', 'approver', 'quality']),
                money=dict(operation='collection', currency='USD', principal_minor=500000, collected_fee_minor=15000,
                           refund_minor=0, reserved_refund_minor=0, refunded_fee_minor=0,
                           payout_minor=0, payment_state='paid_held', journal=[515000, -515000]),
                custody=dict(received=True, receipt_id='receipt-1', watch_id='watch-1',
                             recipient_id='buyer', authorized_recipient='buyer',
                             proof_kind='approved_receipt', return_dispatched=False,
                             collection_state='confirmed', return_instruction_id='return-1'))
        if record['requirement'] == 'allocation_fixed_price':
            for case in cases.values():
                case['money'].update(operation='none', payment_state='unpaid',
                                     collected_fee_minor=0, journal=[])
                case['custody']['received'] = False
        for case in cases.values():
            authority = case['authority']
            authority.update(buyer_id='buyer', organization_id='business', roles={
                role: dict(role=role, actor_id=role, organization_id='business',
                           subject_id='watch-1', active=True, membership_revision=1,
                           current_membership_revision=1, assignment_revision=1,
                           current_assignment_revision=1)
                for role in ('assessor', 'brand_approver', 'quality_reviewer', 'eligibility_reviewer')})
            case['money'].update(business_fee_receivable_minor=25000, retained_terms=dict(
                route='watch', principal_minor=500000, buyer_fee_minor=15000,
                business_fee_minor=25000, total_minor=515000, currency='USD',
                order_id='order-1', quote_id='quote-1', quote_revision=1,
                buyer_id='buyer', watch_id='watch-1'))
            if record['content']['feature'] == 'payment_confirmation':
                case['money']['confirmation'] = dict(
                    case['money']['retained_terms'], operation_id=case['operation_id'],
                    state='paid_held', revision=1)
        if record['content']['feature'] in runner.PAID_WORK_FEATURES:
            for case in cases.values():
                money = case['money']
                money['retained_terms'].update(route='job', buyer_fee_minor=0, total_minor=500000)
                money.update(collected_fee_minor=0, journal=[500000, -500000])
        self.bind_negative(cases['negative'], record)
        self.bind_retry(cases['recovery'], record)
        return dict(schema_version='native-outcome.v1', cases=cases,
                    **{k: record[k] for k in ('requirement', 'source_revision', 'run_id', 'origin')})

    def bind_negative(self, case, record):
        case['money'].update(operation='none', journal=[], refund_minor=0, payout_minor=0)
        case['settlement_state'] = 'held'
        case['hold'] = True
        for name, sequence in [('before', 1), ('after', 2)]:
            case[name] = dict(
                observation_id=name, sequence=sequence, operation_id=case['operation_id'],
                money=copy.deepcopy(case['money']), custody=copy.deepcopy(case['custody']),
                new_effect_ids=copy.deepcopy(case['effects']) if name == 'after' else [],
                **{k: record[k] for k in ('requirement', 'source_revision', 'run_id', 'origin')})

    def bind_retry(self, case, record):
        retained = copy.deepcopy(runner.retained_outcome(case))
        for key, sequence in [('original', 1), ('retry', 2)]:
            case[key] = dict(observation_id=key, sequence=sequence,
                             operation_id=case['operation_id'], outcome=copy.deepcopy(retained),
                             new_effect_ids=[],
                             **{k: record[k] for k in
                                ('requirement', 'source_revision', 'run_id', 'origin')})

    def test_operation_specific_postings_and_hold(self):
        for requirement in ('allocation_fixed_price', 'journey_01_en_light',
                            'journey_26_en_light'):
            row = next(r for r in self.plan['requirements'] if r['id'] == requirement)
            record = dict(requirement=requirement, source_revision='a' * 40,
                          run_id='first', origin='http://localhost:3000', content=row['content'])
            outcome = self.outcome(record)
            if requirement == 'journey_26_en_light':
                outcome['cases']['negative'].update(state='held', effects=['reconciliation_hold'],
                                                    mutated=True, hold=True, settlement_state='held')
            self.bind_negative(outcome['cases']['negative'], record)
            self.bind_retry(outcome['cases']['recovery'], record)
            runner.validate_outcomes(outcome, record)
            changed = copy.deepcopy(outcome)
            changed['cases']['positive']['money']['journal'] = [1, -1]
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)

    def test_retry_provenance_mutations(self):
        row = self.plan['requirements'][0]
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        good = self.outcome(record)
        for observation, field, value in [
                ('original', 'operation_id', 'fresh'), ('retry', 'operation_id', 'fresh'),
                ('retry', 'sequence', 1), ('retry', 'observation_id', 'original'),
                ('retry', 'new_effect_ids', ['duplicate']), ('original', 'outcome', {}),
                ('retry', 'source_revision', 'b' * 40)]:
            changed = copy.deepcopy(good)
            changed['cases']['recovery'][observation][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)

    def test_financial_custody_authority_mutations(self):
        row = next(r for r in self.plan['requirements'] if r['id'] == 'balanced_simulated_journal')
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        good = self.outcome(record)
        runner.validate_outcomes(good, record)
        mutations = [
            ('money', 'journal', [515000, -500000]),
            ('money', 'journal', [0]),
            ('money', 'journal', [1, -1]),
            ('money', 'refunded_fee_minor', 15000),
            ('money', 'refund_minor', 500001),
            ('money', 'reserved_refund_minor', 500001),
            ('money', 'payment_state', 'awaiting_payment'),
            ('money', 'payout_minor', 475000),
            ('custody', 'received', False),
            ('custody', 'receipt_id', ''),
            ('custody', 'watch_id', 'other-watch'),
            ('custody', 'recipient_id', 'other-person'),
            ('custody', 'proof_kind', 'dispatch_scan'),
            ('authority', 'current', False),
            ('authority', 'revision', 1),
        ]
        for group, key, value in mutations:
            changed = copy.deepcopy(good)
            changed['cases']['positive'][group][key] = value
            with self.subTest(group=group, key=key), self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)
        for state in ('invented', 'awaiting_payment'):
            changed = copy.deepcopy(good)
            changed['cases']['positive']['settlement_state'] = state
            if state == 'awaiting_payment':
                changed['cases']['positive']['state'] = 'completed'
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)
        for key, value in [('mutated', True), ('state', 'completed')]:
            changed = copy.deepcopy(good)
            changed['cases']['negative'][key] = value
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)
        changed = copy.deepcopy(good)
        changed['cases']['recovery']['retry_operation_id'] = 'new-operation'
        with self.assertRaises(ValueError):
            runner.validate_outcomes(changed, record)
        for collection in ('declined', 'unknown'):
            changed = copy.deepcopy(good)
            changed['cases']['positive']['custody'].update(
                return_dispatched=True, collection_state=collection,
                return_trip_minor=1000, collected_minor=26000)
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)
        changed = copy.deepcopy(good)
        changed['cases']['positive']['state'] = 'awaiting_payment'
        with self.assertRaises(ValueError):
            runner.validate_outcomes(changed, record)
        with self.assertRaises(ValueError):
            runner.validate_outcomes({}, record)

    def test_refund_and_payout_cannot_dispose_same_principal(self):
        row = next(r for r in self.plan['requirements'] if r['id'] == 'payout_reconciliation')
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        outcome = self.outcome(record)
        for case in outcome['cases'].values():
            case['settlement_state'] = 'paid_out'
            case['money'].update(payout_minor=475000, operation='payout',
                                 journal=[475000, -475000])
        self.bind_negative(outcome['cases']['negative'], record)
        self.bind_retry(outcome['cases']['recovery'], record)
        runner.validate_outcomes(outcome, record)
        for posting in ('none', 'collection'):
            changed = copy.deepcopy(outcome)
            changed['cases']['positive']['money'].update(operation=posting, journal=[])
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)
        for field in ('refund_minor', 'reserved_refund_minor'):
            changed = copy.deepcopy(outcome)
            changed['cases']['positive']['money'][field] = 500000
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)

    def test_refund_postings(self):
        row = next(r for r in self.plan['requirements'] if r['id'] == 'principal_only_refund')
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        good = self.outcome(record)
        for case in good['cases'].values():
            case['settlement_state'] = 'refunded'
            case['refund_authorization'] = dict(operation_id=case['operation_id'], authorized=True,
                                                principal_minor=500000, decision_id='decision-1')
            case['money'].update(operation='refund', refund_minor=500000,
                                 journal=[500000, -500000])
        self.bind_negative(good['cases']['negative'], record)
        self.bind_retry(good['cases']['recovery'], record)
        runner.validate_outcomes(good, record)
        for posting in ('none', 'collection', 'payout'):
            changed = copy.deepcopy(good)
            changed['cases']['positive']['money'].update(operation=posting, journal=[])
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)

    def test_required_collection_without_dispatch(self):
        row = next(r for r in self.plan['requirements'] if r['id'] == 'failed_inspection_collection')
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        good = self.outcome(record)
        for case in good['cases'].values():
            case['custody'].update(return_trip_minor=1000, collected_minor=26000)
        self.bind_negative(good['cases']['negative'], record)
        self.bind_retry(good['cases']['recovery'], record)
        runner.validate_outcomes(good, record)
        for key, value in [('collection_state', 'unknown'), ('collected_minor', 0)]:
            changed = copy.deepcopy(good)
            changed['cases']['positive']['custody'][key] = value
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)

    def test_denial_cannot_post_or_change_custody(self):
        row = self.plan['requirements'][0]
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        good = self.outcome(record)
        for group, field, value in [('money', 'journal', [1, -1]),
                                    ('money', 'operation', 'collection'),
                                    ('money', 'refund_minor', 1),
                                    ('money', 'payout_minor', 1),
                                    ('custody', 'received', True)]:
            changed = copy.deepcopy(good)
            changed['cases']['negative'][group][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)

    def test_refund_requires_execution_and_authorization(self):
        row = next(r for r in self.plan['requirements'] if r['id'] == 'principal_only_refund')
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        with self.assertRaises(ValueError):
            runner.validate_outcomes(self.outcome(record), record)

    def test_confirmation_and_role_binding_mutations(self):
        row = next(r for r in self.plan['requirements']
                   if r['id'] == 'journey_26_en_light')
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        good = self.outcome(record)
        for field, value in [('order_id', 'other'), ('watch_id', 'other'), ('quote_id', 'other'),
                             ('quote_revision', 2), ('buyer_id', 'other'),
                             ('total_minor', 0), ('operation_id', 'other'),
                             ('currency', 'other'), ('state', 'pending')]:
            changed = copy.deepcopy(good)
            case = changed['cases']['positive']
            case['money']['confirmation'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                runner.validate_economics(case, True)
        for role in good['cases']['positive']['authority']['roles']:
            for field, value in [('actor_id', 'buyer'), ('organization_id', 'other'),
                                 ('subject_id', 'other'), ('active', False),
                                 ('current_membership_revision', 2),
                                 ('current_assignment_revision', 2),
                                 ('actor_id', 'assessor')]:
                if role == 'assessor' and value == 'assessor':
                    continue
                case = copy.deepcopy(good['cases']['positive'])
                case['authority']['roles'][role][field] = value
                with self.subTest(role=role, field=field), self.assertRaises(ValueError):
                    runner.validate_authority(case['authority'], case)
        case = copy.deepcopy(good['cases']['positive'])
        case['money'].update(operation='none', principal_minor=0,
                             collected_fee_minor=0, journal=[])
        with self.assertRaises(ValueError):
            runner.validate_economics(case, True)

    def test_exact_watch_and_job_components(self):
        row = self.plan['requirements'][0]
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        for route in ('watch', 'job'):
            for principal in (500000, 10, 1):
                case = self.outcome(record)['cases']['positive']
                money = case['money']
                buyer_fee = (principal * 3 + 50) // 100 if route == 'watch' else 0
                fee = (principal * 5 + 50) // 100
                money.update(principal_minor=principal, business_fee_receivable_minor=fee)
                money['retained_terms'].update(route=route, principal_minor=principal,
                    buyer_fee_minor=buyer_fee, business_fee_minor=fee,
                    total_minor=principal + buyer_fee)
                runner.validate_economics(case)
                for field in ('buyer_fee_minor', 'business_fee_minor', 'total_minor'):
                    changed = copy.deepcopy(case)
                    changed['money']['retained_terms'][field] += 1
                    with self.subTest(route=route, field=field), self.assertRaises(ValueError):
                        runner.validate_economics(changed)

    def test_noncommercial_and_purchase_authority(self):
        for requirement in ('journey_01_en_light', 'journey_18_en_light',
                            'allocation_fixed_price'):
            row = next(r for r in self.plan['requirements'] if r['id'] == requirement)
            record = dict(requirement=requirement, source_revision='a' * 40,
                          run_id='first', origin='http://localhost:3000', content=row['content'])
            outcome = self.outcome(record)
            for case in outcome['cases'].values():
                case['authority'].pop('roles')
                if requirement != 'allocation_fixed_price':
                    case['money'].update(principal_minor=0, collected_fee_minor=0,
                                         operation='none', journal=[], payment_state='unpaid')
                    case['money'].pop('retained_terms')
                    case['money'].pop('business_fee_receivable_minor')
                    case['custody']['received'] = False
                    case['settlement_state'] = 'not_applicable'
            self.bind_negative(outcome['cases']['negative'], record)
            self.bind_retry(outcome['cases']['recovery'], record)
            runner.validate_outcomes(outcome, record)
            changed = copy.deepcopy(outcome)
            changed['cases']['positive']['authority']['current'] = False
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)

    def test_commercial_terms_bind_observed_buyer_and_watch(self):
        for row in self.plan['requirements']:
            record = dict(requirement=row['id'], source_revision='a' * 40,
                          run_id='first', origin='http://localhost:3000', content=row['content'])
            good = self.outcome(record)
            for kind in ('positive', 'negative', 'recovery'):
                runner.validate_economics(good['cases'][kind])
                for field in ('buyer_id', 'watch_id'):
                    changed = copy.deepcopy(good)
                    case = changed['cases'][kind]
                    case['money']['retained_terms'][field] = 'other'
                    if kind == 'negative':
                        self.bind_negative(case, record)
                    if kind == 'recovery':
                        self.bind_retry(case, record)
                    with self.subTest(requirement=row['id'], kind=kind, field=field), \
                            self.assertRaisesRegex(ValueError, 'retained_subject_binding'):
                        runner.validate_economics(case)
                    if row['content']['feature'] in runner.PAID_WORK_FEATURES:
                        with self.assertRaisesRegex(ValueError, 'retained_subject_binding'):
                            runner.validate_outcomes(changed, record)

    def test_paid_job_keeps_review_and_economics_requirements(self):
        row = next(r for r in self.plan['requirements'] if r['id'] == 'paid_customization')
        record = dict(requirement=row['id'], source_revision='a' * 40,
                      run_id='first', origin='http://localhost:3000', content=row['content'])
        good = self.outcome(record)
        runner.validate_outcomes(good, record)
        for group, field, value in [('authority', 'roles', {}),
                                    ('money', 'principal_minor', 0)]:
            changed = copy.deepcopy(good)
            changed['cases']['positive'][group][field] = value
            with self.assertRaises(ValueError):
                runner.validate_outcomes(changed, record)

    def test_paid_work_completion_mutations(self):
        for feature in sorted(runner.PAID_WORK_FEATURES):
            row = next(r for r in self.plan['requirements'] if r['id'] == feature
                       or r['content']['feature'] == feature)
            record = dict(requirement=row['id'], source_revision='a' * 40,
                          run_id='first', origin='http://localhost:3000', content=row['content'])
            good = self.outcome(record)
            runner.validate_outcomes(good, record)
            for kind in ('positive', 'recovery'):
                for group, field, value in [
                        ('money', 'payment_state', 'unpaid'),
                        ('money', 'operation', 'none'),
                        ('custody', 'received', False),
                        (None, 'quality', 'failed'),
                        (None, 'window_expired', False),
                        (None, 'hold', True),
                        (None, 'settlement_state', 'awaiting_payment')]:
                    changed = copy.deepcopy(good)
                    case = changed['cases'][kind]
                    (case[group] if group else case)[field] = value
                    if field in {'payment_state', 'operation'}:
                        case['money'].update(operation='none', journal=[])
                        if field == 'payment_state':
                            case['money']['collected_fee_minor'] = 0
                    if kind == 'recovery':
                        self.bind_retry(case, record)
                    with self.subTest(feature=feature, kind=kind, field=field), \
                            self.assertRaises(ValueError):
                        runner.validate_outcomes(changed, record)

    def test_paid_work_rejects_watch_route_substitution(self):
        for row in self.plan['requirements']:
            if row['content']['feature'] not in runner.PAID_WORK_FEATURES:
                continue
            record = dict(requirement=row['id'], source_revision='a' * 40,
                          run_id='first', origin='http://localhost:3000', content=row['content'])
            good = self.outcome(record)
            runner.validate_outcomes(good, record)
            for kind in ('positive', 'negative', 'recovery'):
                changed = copy.deepcopy(good)
                case = changed['cases'][kind]
                money = case['money']
                money['retained_terms'].update(route='watch', buyer_fee_minor=15000,
                                               total_minor=515000)
                money['collected_fee_minor'] = 15000
                if money['operation'] == 'collection':
                    money['journal'] = [515000, -515000]
                if kind == 'negative':
                    self.bind_negative(case, record)
                if kind == 'recovery':
                    self.bind_retry(case, record)
                with self.subTest(requirement=row['id'], kind=kind), \
                        self.assertRaisesRegex(ValueError, 'required_job_route'):
                    runner.validate_outcomes(changed, record)

    def test_service_work_role_mutations(self):
        for feature in sorted(runner.SERVICE_WORK_FEATURES):
            row = next(r for r in self.plan['requirements'] if r['id'] == feature)
            record = dict(requirement=row['id'], source_revision='a' * 40,
                          run_id='first', origin='http://localhost:3000', content=row['content'])
            good = self.outcome(record)
            for case in good['cases'].values():
                case['authority']['roles'].pop('eligibility_reviewer')
            self.bind_retry(good['cases']['recovery'], record)
            runner.validate_outcomes(good, record)
            for kind in ('positive', 'negative', 'recovery'):
                for role in ('assessor', 'brand_approver', 'quality_reviewer'):
                    for field, value in [(None, None), ('actor_id', 'buyer'),
                                         ('actor_id', 'assessor'), ('active', False),
                                         ('organization_id', 'other'), ('subject_id', 'other'),
                                         ('current_membership_revision', 2),
                                         ('current_assignment_revision', 2)]:
                        if role == 'assessor' and field == 'actor_id' and value == 'assessor':
                            continue
                        changed = copy.deepcopy(good)
                        case = changed['cases'][kind]
                        roles = case['authority']['roles']
                        if field is None:
                            roles.pop(role)
                        else:
                            roles[role][field] = value
                        if kind == 'recovery':
                            self.bind_retry(case, record)
                        with self.subTest(feature=feature, kind=kind, role=role, field=field), \
                                self.assertRaises(ValueError):
                            runner.validate_outcomes(changed, record)

    def test_missing_duplicate_and_unknown_evidence(self):
        for records in ([], [{'requirement': 'unknown'}],
                        [{'requirement': 'allocation_job'}] * 2):
            report = runner.assemble(self.plan, records, Path('/tmp'), 'http://localhost:3000', 'first')
            self.assertFalse(report['complete'])
            self.assertEqual(len(report['missing_capabilities']), 291)

    def test_claimed_success_cannot_complete_acceptance(self):
        plan = copy.deepcopy(self.plan)
        for row in plan['requirements']:
            row.update(entrypoint='tests/provider/scenario.json', source_revision='a' * 40)
        with patch.object(runner, 'validate_evidence', return_value=None):
            report = runner.assemble(plan, [], Path('/tmp'), 'http://localhost:3000', 'first')
        self.assertFalse(report['complete'])
        self.assertIn('provider_outcome_contracts_deferred', report['errors'])

    def test_pure_cli_and_missing_route(self):
        with patch('socket.socket', side_effect=AssertionError('network')), \
                patch('subprocess.Popen', side_effect=AssertionError('process')), \
                patch('builtins.print'):
            self.assertEqual(runner.main(['--check-plan']), 0)
            with tempfile.TemporaryDirectory() as folder:
                self.assertEqual(runner.main(['--origin', 'http://localhost:3000',
                                              '--run-dir', folder, '--require-all']), 1)


if __name__ == '__main__':
    unittest.main()
