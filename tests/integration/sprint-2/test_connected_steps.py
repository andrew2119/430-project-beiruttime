"""Producer transport checks; these results never certify connected execution."""
import tempfile
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from connected_runner import MissingCapability, Runner
from connected_steps import absence_status, resolve


class ProducerExecutionTests(unittest.TestCase):
    def runner(self, folder):
        walk = SimpleNamespace(state={'accounts': {'brand': {'account': {'id': 'test-actor'}}}}, save=Mock())
        runner = Runner(folder, walk, 'test-revision')
        runner.connected.inputs = Mock(return_value={'work': {
            'actor': 'brand', 'subject': 'test-job', 'body': {
                'operation_id': 'test-placeholder', 'actor_id': 'test-actor',
                'organization_id': 'test-business', 'subject_id': 'test-job',
                'expected_revision': 0, 'note': 'Sample actual observation'}}})
        return runner

    def test_absence_status_is_specific_to_work(self):
        self.assertEqual(absence_status('work'), (403,))
        for kind in ('assessment', 'allocation', 'custody', 'quality'):
            self.assertEqual(absence_status(kind), (404,))

    def test_absent_work_does_not_allow_denied_command_to_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = self.runner(folder)
            runner.call = Mock(side_effect=[{}, RuntimeError('test-denied-command')])
            with self.assertRaises(MissingCapability) as error:
                runner.connected.execute('service', 'work')
            self.assertEqual(error.exception.names, ['service.work.producer'])
            self.assertEqual(runner.call.call_args_list[0].kwargs['expected'], (403,))
            self.assertEqual(runner.call.call_args_list[1].kwargs['expected'], (200, 201, 202))
            self.assertNotIn('state', runner.walk.state['e06_jobs']['service']['work'])

    def test_typed_references_preserve_integer_and_boolean_types(self):
        self.assertEqual(resolve({'revision': {'reference': 'steps.scope.revision'},
                                  'permission': {'reference': 'steps.permission'}},
                                 {'steps': {'scope': {'revision': 7}, 'permission': True}}),
                         {'revision': 7, 'permission': True})

    def test_current_command_and_receipt_bind_same_operation_and_business(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = self.runner(folder)
            def respond(service, method, route, actor, body=None, **kwargs):
                if kwargs.get('expected') in ((403,), (404,)):
                    return {}
                binding = runner.walk.state['e06_bindings']['service:work']
                return {**binding, 'state': 'recorded', 'revision': 1}
            runner.call = Mock(side_effect=respond)
            result = runner.connected.execute('service', 'work')
            self.assertEqual(runner.call.call_args_list[0].kwargs['expected'], (403,))
            self.assertNotIn('expected', runner.call.call_args_list[2].kwargs)
            writes = [call for call in runner.call.call_args_list if call.args[1] == 'POST']
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0].kwargs['key'], result['operation_id'])
            self.assertEqual(writes[0].args[2], '/internal/v1/authorized-work/commands?organization_id=test-business')
            self.assertIn(result['operation_id'], runner.call.call_args_list[2].args[2])
            self.assertEqual(runner.walk.state['e06_jobs']['service']['work'], result)

    def test_interrupted_delivery_reuses_binding_before_new_current_values(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = self.runner(folder)
            runner.call = Mock(side_effect=[{}, TimeoutError()])
            with self.assertRaises(MissingCapability):
                runner.connected.execute('service', 'work')
            original = runner.walk.state['e06_bindings']['service:work'].copy()
            runner.connected.inputs.return_value['work']['body']['expected_revision'] = 9
            def respond(*args, **kwargs):
                return {**original, 'state': 'recorded', 'revision': 1}
            runner.call = Mock(side_effect=respond)
            runner.connected.execute('service', 'work')
            self.assertEqual(runner.call.call_args_list[0].args[4], original)
            self.assertEqual(runner.call.call_count, 2)

    def test_changed_private_receipt_and_pending_outcome_cannot_pass(self):
        for change in ({'organization_id': 'test-other'}, {'state': 'pending'}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                runner = self.runner(folder)
                def respond(*args, **kwargs):
                    if kwargs.get('expected') in ((403,), (404,)):
                        return {}
                    return {**runner.walk.state['e06_bindings']['service:work'],
                            'state': 'recorded', 'revision': 1, **change}
                runner.call = Mock(side_effect=respond)
                with self.assertRaises(MissingCapability):
                    runner.connected.execute('service', 'work')

    def test_supplied_outcome_is_refused_before_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = self.runner(folder)
            runner.connected.inputs.return_value['work']['body']['state'] = 'recorded'
            runner.call = Mock()
            with self.assertRaises(MissingCapability):
                runner.connected.execute('service', 'work')
            runner.call.assert_not_called()

    def test_review_and_grant_use_distinct_references_and_current_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = self.runner(folder)
            runner.connected.inputs.return_value.update({
                'eligibility_review': {'actor': 'brand', 'subject': 'test-consent', 'body': {
                    'operation_id': 'test-placeholder', 'consent_id': 'test-consent',
                    'kind': 'review', 'verdict': 'eligible', 'expected_revision': 0}},
                'eligibility': {'actor': 'brand', 'subject': 'test-consent', 'body': {
                    'operation_id': 'test-placeholder', 'consent_id': 'test-consent',
                    'kind': 'prepare', 'use': 'approval',
                    'expected_revision': {'reference': 'steps.eligibility_review.revision'}}}})
            def respond(service, method, route, actor, body=None, **kwargs):
                if kwargs.get('expected') in ((403,), (404,)):
                    return {}
                if method == 'POST':
                    return {**body, 'state': 'eligible' if body['kind'] == 'review' else 'prepared',
                            'revision': body['expected_revision'] + 1}
                for binding in runner.walk.state['e06_bindings'].values():
                    if binding['operation_id'] in route:
                        return {**binding, 'state': 'eligible' if binding['kind'] == 'review' else 'prepared',
                                'revision': binding['expected_revision'] + 1}
                self.fail('Missing retained command')
            runner.call = Mock(side_effect=respond)
            runner.connected.execute('customization', 'eligibility_review')
            runner.connected.execute('customization', 'eligibility')
            bindings = runner.walk.state['e06_bindings']
            self.assertNotEqual(bindings['customization:eligibility_review']['operation_id'],
                                bindings['customization:eligibility']['operation_id'])
            self.assertEqual(bindings['customization:eligibility']['expected_revision'], 1)
            bindings['customization:eligibility']['expected_revision'] = 0
            with self.assertRaises(MissingCapability):
                runner.connected.prepare('customization', 'eligibility')

    def test_restart_control_requires_acknowledged_undelivered_operation(self):
        import json
        request = {'schema_version': 1, 'journey': 'service', 'case': 'restart',
                   'phase': 'restart', 'operation_id': 'test-operation', 'acknowledged': True}
        proof = {'operation_id': 'test-operation', 'acknowledged': True,
                 'response_delivered': False}
        for interruption in (None, {**proof, 'response_delivered': True},
                             {**proof, 'operation_id': 'test-other'}, proof):
            with self.subTest(interruption=interruption), tempfile.TemporaryDirectory() as folder:
                runner = self.runner(folder)
                channel = Mock()
                answer = dict(request)
                if interruption is not None:
                    answer['interruption'] = interruption
                channel.recv.return_value = json.dumps(answer).encode() + b'\n'
                with patch('connected_steps.socket.socket') as stream:
                    stream.return_value.__enter__.return_value = channel
                    if interruption == proof:
                        runner.connected.control('service', 'restart', 'restart', 'test-operation')
                    else:
                        with self.assertRaises(MissingCapability) as error:
                            runner.connected.control('service', 'restart', 'restart', 'test-operation')
                        self.assertEqual(error.exception.names, ['service.restart.acknowledged_interruption'])

    def test_missing_control_is_named_and_does_not_certify_case(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = self.runner(folder)
            with self.assertRaises(MissingCapability) as failure:
                runner.connected.control('service', 'restart', 'arm', 'test-operation')
            self.assertEqual(failure.exception.names, ['native.restart.arm_control'])

    def test_job_operations_run_in_order_through_payment_receipt_and_release(self):
        for journey in ('service', 'customization'):
            with self.subTest(journey=journey), tempfile.TemporaryDirectory() as folder:
                runner = self.runner(folder)
                runner.walk.state['e06_service'] = {'actor': 'buyer-b'}
                steps = runner.connected
                sequence = []
                def execute(_, stage):
                    sequence.append(stage)
                    return {'order_id': 'test-order'}
                def quote(_):
                    sequence.append('quote')
                    steps.facts(journey)['steps']['quote'] = {
                        'id': 'test-quote', 'decision': {'amounts': {'payable_minor': 10000}}}
                steps.execute = Mock(side_effect=execute)
                steps.quote = Mock(side_effect=quote)
                runner.call = Mock(return_value={'order': {'quote_id': 'test-quote', 'total_minor': 10000}})
                runner.payment = Mock(side_effect=lambda _: sequence.append('payment'))
                runner.receipt_and_release = Mock(side_effect=lambda _: sequence.append('receipt_release'))
                steps.journey(journey)
                buyer = 'buyer-b' if journey == 'service' else 'buyer-a'
                self.assertEqual(runner.call.call_args.args[3], buyer)
                self.assertEqual(runner.payment.call_args.args[0]['winner'], buyer)
                prefix = (['assessment', 'quote', 'consent', 'eligibility_review', 'eligibility', 'approval']
                          if journey == 'customization' else ['service_assessment', 'quote', 'scope'])
                self.assertEqual(sequence, prefix + ['allocation', 'payment',
                    'authorization' if journey == 'customization' else 'repair_authorization',
                    'work', 'quality', 'custody', 'receipt_release'])

class FaultExecutionTests(unittest.TestCase):
    def test_every_fault_reaches_current_requests_and_preserves_reference(self):
        cases = ('denied', 'stale', 'cross_account', 'cross_business', 'timeout',
                 'lost_response', 'duplicate', 'restart', 'recovery')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                runner = Runner(folder, SimpleNamespace(state={'accounts': {
                    'brand': {'account': {'id': 'test-brand'}},
                    'buyer-b': {'account': {'id': 'test-buyer'}}}}, save=Mock()), 'test-revision')
                steps = runner.connected
                steps.inputs = Mock(return_value={'cases': {case: {
                    'guard': 'work', 'other_actor': 'buyer-b', 'producer': 'work'}}})
                contract = Path(__file__).resolve().parents[3] / 'packages/contracts-service/authorized-work'
                binding = json.loads((contract / 'fixtures.v1.json').read_text())['cases'][0]['command']
                binding.update(operation_id='test-operation', expected_revision=1)
                def prepare(journey, name, supplied=None):
                    guard = name == 'work'
                    return ('service-operations', '/command', '/guard' if guard else '/receipt',
                            'brand', {**binding, 'operation_id': 'test-guard'} if guard else binding,
                            'test-guard' if guard else 'test-operation', 'recorded')
                steps.prepare = Mock(side_effect=prepare)
                steps.control = Mock()
                steps.duplicate_callback = Mock()
                steps.journey = Mock()
                pending = {**binding, 'state': 'pending', 'pending_reason': 'source_unavailable',
                           'next_actor': 'test-owner', 'next_action': 'Retry source read', 'next_review_at': '2026-11-17T12:00:00Z'}
                schema = json.loads((contract / 'operation.schema.v1.json').read_text())
                receipt = {key: value for key, value in binding.items()
                           if key in schema['properties']}
                receipt.update(state='recorded', revision=2, pending_reason=None,
                    recorded_at='2026-11-17T12:00:00Z', since='2026-11-17T12:00:00Z',
                    escalation_at='2026-11-18T12:00:00Z', release_eligible=False)
                self.assertEqual(set(schema['required']) - set(receipt), set())
                self.assertNotIn('note', receipt)
                delivery_count = 0
                def respond(service, method, route, actor, body=None, **kwargs):
                    nonlocal delivery_count
                    if kwargs.get('expected') in ((403, 404), (403,), (404,)):
                        return {}
                    if route == '/guard':
                        return {'state': 'recorded', 'operation_id': 'test-guard'}
                    if kwargs.get('expected') == (409,):
                        return {'error': {'code': 'stale_revision'}}
                    if kwargs.get('expected') == (403, 409):
                        return {}
                    if method == 'POST':
                        delivery_count += 1
                        if case == 'restart' and delivery_count == 1:
                            import httpx
                            raise httpx.ReadError('test-interrupted-response')
                        return pending if case in ('timeout', 'recovery') and delivery_count == 1 else receipt
                    return pending if case in ('timeout', 'recovery') and delivery_count == 1 else receipt
                runner.call = Mock(side_effect=respond)
                steps.fault_case('service', case)
                steps.journey.assert_called_once_with('service')
                writes = [call for call in runner.call.call_args_list if call.args[1] == 'POST']
                self.assertTrue(writes)
                self.assertTrue(all(call.kwargs['key'] ==
                    ('test-guard' if case == 'cross_account' else 'test-operation') for call in writes))
                if case == 'cross_account':
                    self.assertEqual(writes[0].args[3:5], ('buyer-b', {**binding, 'operation_id': 'test-guard'}))
                if case in ('denied', 'stale', 'cross_business', 'timeout', 'restart', 'recovery'):
                    phases = [call.args[2] for call in steps.control.call_args_list]
                    self.assertEqual(phases[0], 'arm')
                    self.assertEqual(phases[-1], 'restore')
                if case == 'duplicate':
                    steps.duplicate_callback.assert_called_once_with('service', 'test-operation')

    def test_matching_foreign_lookup_and_replay_cannot_pass(self):
        for case in ('lost_response', 'duplicate'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                runner = Runner(folder, SimpleNamespace(state={}, save=Mock()), 'test-revision')
                steps = runner.connected
                steps.inputs = Mock(return_value={'cases': {case: {'guard': 'work'}}})
                body = {'operation_id': 'test-operation', 'actor_id': 'test-actor',
                        'subject_id': 'test-subject'}
                steps.prepare = Mock(return_value=('service-operations', '/command', '/receipt',
                    'brand', body, 'test-operation', 'recorded'))
                foreign = {'operation_id': 'test-other-operation', 'actor_id': 'test-other-actor',
                           'subject_id': 'test-other-subject', 'state': 'recorded'}
                runner.call = Mock(side_effect=[{}, {'state': 'recorded'}, foreign, foreign, foreign])
                steps.journey = Mock()
                steps.duplicate_callback = Mock()
                with self.assertRaises(MissingCapability) as error:
                    steps.fault_case('service', case)
                self.assertEqual(error.exception.names, ['service.' + case + '.exact_receipt_binding'])
                steps.journey.assert_not_called()
                steps.duplicate_callback.assert_not_called()

    def test_fault_receipts_require_retained_operation_and_command_fields(self):
        body = {'operation_id': 'test-operation', 'actor_id': 'test-actor',
                'subject_id': 'test-subject', 'organization_id': 'test-business',
                'watch_id': 'test-watch', 'quote_revision': 3,
                'expected_revision': 0, 'note': 'test-observation'}
        for case in ('lost_response', 'duplicate', 'restart', 'timeout', 'recovery'):
            for field in body:
                if field == 'expected_revision':
                    continue
                for changed in (True, False):
                    with self.subTest(case=case, field=field, changed=changed), tempfile.TemporaryDirectory() as folder:
                        runner = Runner(folder, SimpleNamespace(state={}), 'test-revision')
                        receipt = {**body, 'state': 'recorded', 'revision': 1}
                        runner.connected.verify_fault_receipt('service', case, body,
                                                              'test-operation', receipt)
                        if changed:
                            receipt[field] = 'test-other'
                        else:
                            del receipt[field]
                        with self.assertRaises(MissingCapability) as error:
                            runner.connected.verify_fault_receipt('service', case, body,
                                                                  'test-operation', receipt)
                        self.assertEqual(error.exception.names,
                                         ['service.' + case + '.exact_receipt_binding'])

    def test_work_receipt_checks_every_retained_binding_without_observations(self):
        contract = Path(__file__).resolve().parents[3] / 'packages/contracts-service/authorized-work'
        body = json.loads((contract / 'fixtures.v1.json').read_text())['cases'][0]['command']
        schema = json.loads((contract / 'operation.schema.v1.json').read_text())
        receipt = {key: value for key, value in body.items() if key in schema['properties']}
        for case in ('lost_response', 'duplicate', 'restart', 'timeout', 'recovery'):
            with tempfile.TemporaryDirectory() as folder:
                steps = Runner(folder, SimpleNamespace(state={}), 'test-revision').connected
                steps.verify_fault_receipt('service', case, body, body['operation_id'], receipt, 'work')
                for field in receipt:
                    for changed in ({key: value for key, value in receipt.items() if key != field},
                                    {**receipt, field: 'test-other'}):
                        with self.subTest(case=case, field=field), self.assertRaises(MissingCapability):
                            steps.verify_fault_receipt('service', case, body, body['operation_id'], changed, 'work')

    def test_incomplete_pending_metadata_cannot_certify_timeout_or_recovery(self):
        for case in ('timeout', 'recovery'):
            for field in ('pending_reason', 'next_actor', 'next_action', 'next_review_at'):
                for value in (None, ''):
                    with self.subTest(case=case, field=field, value=value), tempfile.TemporaryDirectory() as folder:
                        runner = Runner(folder, SimpleNamespace(state={}, save=Mock()), 'test-revision')
                        steps = runner.connected
                        steps.inputs = Mock(return_value={'cases': {case: {'guard': 'work'}}})
                        steps.prepare = Mock(return_value=('service-operations', '/command', '/receipt',
                            'brand', {'operation_id': 'test-operation'}, 'test-operation', 'recorded'))
                        steps.control = Mock()
                        pending = {'operation_id': 'test-operation', 'state': 'pending',
                            'pending_reason': 'source_unavailable', 'next_actor': 'test-owner',
                            'next_action': 'Retry source read', 'next_review_at': '2026-11-17T12:00:00Z'}
                        if value is None:
                            del pending[field]
                        else:
                            pending[field] = value
                        runner.call = Mock(side_effect=[{}, {'state': 'recorded'}, pending])
                        with self.assertRaises(MissingCapability) as error:
                            steps.fault_case('service', case)
                        self.assertEqual(error.exception.names,
                            ['service.' + case + '.responsible_pending_receipt'])
                        self.assertEqual([call.args[2] for call in steps.control.call_args_list],
                                         ['arm', 'restore'])

    def test_restart_with_complete_response_cannot_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(folder, SimpleNamespace(state={}, save=Mock()), 'test-revision')
            steps = runner.connected
            steps.inputs = Mock(return_value={'cases': {'restart': {'guard': 'work'}}})
            steps.prepare = Mock(return_value=('service-operations', '/command', '/receipt',
                'brand', {'operation_id': 'test-operation'}, 'test-operation', 'recorded'))
            steps.control = Mock()
            runner.call = Mock(side_effect=[{}, {'state': 'recorded'}, {'state': 'recorded'}])
            with self.assertRaises(MissingCapability) as error:
                steps.fault_case('service', 'restart')
            self.assertEqual(error.exception.names, ['service.restart.response_was_delivered'])
            self.assertEqual([call.args[2] for call in steps.control.call_args_list], ['arm', 'restore'])

    def test_arbitrary_conflict_cannot_certify_changed_source(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(folder, SimpleNamespace(state={}, save=Mock()), 'test-revision')
            steps = runner.connected
            steps.inputs = Mock(return_value={'cases': {'stale': {'guard': 'work'}}})
            steps.prepare = Mock(return_value=('service-operations', '/command', '/receipt',
                'brand', {'expected_revision': 1}, 'test-operation', 'recorded'))
            steps.control = Mock()
            runner.call = Mock(side_effect=[{}, {'state': 'recorded'}, {'error': {'code': 'operation_conflict'}}])
            with self.assertRaises(MissingCapability) as error:
                steps.fault_case('service', 'stale')
            self.assertEqual(error.exception.names, ['service.stale.authoritative_source_rejection'])
            self.assertEqual(steps.control.call_args.args[2], 'restore')

class QuoteAndCallbackTests(unittest.TestCase):
    def test_assessed_quote_acceptance_uses_current_full_total_and_terms(self):
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={'e06_service': {'actor': 'buyer-b', 'result': {'request_id': 'test-request'}}}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            steps = runner.connected
            steps.inputs = Mock(return_value={'quote': {'actor': 'dealer', 'body': {
                'source_id': 'test-request', 'source_revision': 1, 'assessment_id': 'test-assessment',
                'assessment_revision': 2, 'currency': 'USD', 'schedule_id': 'usd-job-v2'}}})
            quote = {'id': 'test-quote', 'revision': 3, 'currency': 'USD',
                     'full_total': {'payable_minor': 12000}, 'terms_digest': 'test-digest',
                     'lines': [{'id': 'test-line'}]}
            accepted = {**quote, 'state': 'accepted', 'decision': {'amounts': {'payable_minor': 12000}}}
            runner.call = Mock(side_effect=[{}, {'status': 'succeeded', 'quote': quote},
                quote, {'status': 'succeeded', 'quote': accepted}, accepted])
            steps.quote('service')
            for index in (2, 3, 4):
                self.assertEqual(runner.call.call_args_list[index].args[3], 'buyer-b')
            acceptance = runner.call.call_args_list[3]
            self.assertEqual(acceptance.args[4], {'quote_revision': 3,
                'selected_line_ids': ['test-line'], 'payable_minor': 12000,
                'terms_digest': 'test-digest', 'accept_assessment_fee': True, 'accept_return_fee': True})
            self.assertEqual(steps.facts('service')['steps']['quote'], accepted)

    def test_exact_callback_bytes_reach_signed_receiver_twice(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={'reservation': {'winner': 'buyer-a', 'resource_id': 'test-order'},
                'accounts': {'buyer-a': {'account': {'id': 'test-buyer'}}}}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            callback = {'order_id': 'test-order', 'attempt_id': 'test-attempt', 'buyer_id': 'test-buyer',
                'quote_id': 'test-quote', 'quote_revision': 3, 'currency': 'USD',
                'total_minor': 12000, 'outcome': 'confirmed'}
            raw = json.dumps(callback, separators=(',', ':'))
            runner.connected.control = Mock(return_value={'raw': raw, 'signature': 'test-signature'})
            checkout = {'order': {'state': 'paid_held', 'quote_id': 'test-quote', 'total_minor': 12000},
                        'quote': {'revision': 3}, 'attempts': [{'id': 'test-attempt'}]}
            runner.call = Mock(side_effect=[checkout, {}, {}, checkout])
            runner.connected.duplicate_callback('protected_purchase', 'test-operation')
            deliveries = runner.call.call_args_list[1:3]
            self.assertTrue(all(call.args[:3] == ('orders', 'POST', '/callbacks/v1/simulated') for call in deliveries))
            self.assertTrue(all(call.kwargs['content'] == raw.encode() for call in deliveries))
            self.assertTrue(all(call.kwargs['headers']['X-BT-Signature'] == 'test-signature' for call in deliveries))

    def test_wrong_callback_binding_is_refused_before_receiver(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={'reservation': {'winner': 'buyer-a', 'resource_id': 'test-order'},
                'accounts': {'buyer-a': {'account': {'id': 'test-buyer'}}}}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            runner.connected.control = Mock(return_value={'raw': json.dumps({'order_id': 'test-other'}),
                                                          'signature': 'test-signature'})
            runner.call = Mock(return_value={'order': {'state': 'paid_held', 'quote_id': 'test-quote', 'total_minor': 12000},
                'quote': {'revision': 3}, 'attempts': [{'id': 'test-attempt'}]})
            with self.assertRaises(MissingCapability) as failure:
                runner.connected.duplicate_callback('protected_purchase', 'test-operation')
            self.assertEqual(failure.exception.names, ['protected_purchase.duplicate.callback_binding'])
            runner.call.assert_called_once()


if __name__ == '__main__':
    unittest.main()
