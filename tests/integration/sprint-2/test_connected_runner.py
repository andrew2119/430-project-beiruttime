"""Request and evidence contracts; no connected certification."""
import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from connected_runner import (Runner, MissingCapability, auction_request,
                              quote_request, payment_request, private_json,
                              maintenance_request, release_request, attempt_request,
                              submission_request, load_walkthrough, sample_options)


class ConnectedRunnerTests(unittest.TestCase):
    def test_payment_request_binds_current_revision_and_local_method(self):
        self.assertEqual(payment_request({'currency': 'USD', 'total_minor': 515000, 'revision': 7}),
                         {'expected_revision': 7, 'route': 'card'})
        for field, value in [('currency', 'invalid'), ('total_minor', True),
                             ('total_minor', -1), ('total_minor', 1.5), ('revision', True)]:
            order = {'currency': 'USD', 'total_minor': 515000, 'revision': 7}
            order[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                payment_request(order)

    def test_attempt_accepts_retained_unreviewed_winner_quote(self):
        order = dict(currency='USD', total_minor=412000, revision=7)
        self.assertEqual(attempt_request(order, {'revision': 3}), {
            'expected_revision': 7, 'route': 'card', 'quote_revision': 3,
            'total_minor': 412000, 'currency': 'USD'})
        with self.assertRaises(ValueError):
            attempt_request(order, {'revision': True})

    def test_payment_delivers_explicit_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            order = dict(currency='USD', total_minor=412000, revision=7,
                         state='awaiting_payment', notified_at='test-notice', deadline='test-deadline')
            walk = SimpleNamespace(state={'reservation': dict(winner='buyer-a',
                resource_id='test-order', quote={'payable_minor': 412000})}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            runner.call = Mock(side_effect=[
                {'order': order, 'quote': {'revision': 3}, 'payable': True},
                {'status': 'succeeded', 'order': {**order, 'revision': 8}},
                {'status': 'succeeded', 'attempt': {'id': 'test-attempt'}}, {},
                {'order': {**order, 'state': 'paid_held'}}])
            runner.payment()
            self.assertEqual(runner.call.call_args_list[2].args[4], {
                'expected_revision': 8, 'route': 'card', 'quote_revision': 3,
                'total_minor': 412000, 'currency': 'USD'})

    def test_payment_boundary_cases_observe_unchanged_checkout(self):
        for case in ('stale', 'denied', 'cross_business', 'duplicate', 'recovery'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                checkout = {'order': dict(state='paid_held', currency='USD',
                    total_minor=412000, revision=9), 'quote': {'revision': 3},
                    'attempts': [{'id': 'test-attempt'}]}
                binding = dict(expected_revision=8, route='card', quote_revision=3,
                               total_minor=412000, currency='USD')
                walk = SimpleNamespace(state={'reservation': dict(winner='buyer-a',
                    resource_id='test-order'), 'e06_bindings': {'attempt:test-order': binding}}, save=Mock())
                runner = Runner(folder, walk, 'test-revision')
                def respond(service, method, route, actor=None, body=None, **kwargs):
                    if kwargs.get('expected') == (403, 404):
                        return {}
                    if method == 'GET':
                        return checkout
                    if route.endswith('/payment-method'):
                        self.assertEqual(body['expected_revision'], 10)
                        return {'status': 'denied', 'code': 'stale_revision'}
                    if route.endswith('/payment-attempts'):
                        self.assertEqual(body, binding)
                        return {'status': 'succeeded', 'attempt': {'id': 'test-attempt'}}
                    return {}
                runner.call = Mock(side_effect=respond)
                runner.payment_boundary_case('protected_purchase', case)
                self.assertGreaterEqual(runner.call.call_count, 3)
                if case == 'cross_business':
                    self.assertEqual({call.args[3] for call in runner.call.call_args_list
                        if call.kwargs.get('expected')}, {'dealer', 'brand'})

    def test_private_atomic_summary_and_redaction(self):
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={})
            runner = Runner(folder, walk, 'test-revision')
            def missing():
                walk.state['call_journal'] = {'test-key': {'operation_id': 'test-operation'}}
                raise RuntimeError('test-private-password')
            self.assertFalse(runner.record('protected_purchase.positive', missing))
            path = Path(folder) / 'scenarios/e06/summary.json'
            content = path.read_text()
            self.assertNotIn('test-private-password', content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            summary = json.loads(content)
            self.assertEqual(summary['state'], 'failed')
            row = summary['scenarios'][0]
            self.assertEqual(row['operation_ids'], ['test-operation'])
            self.assertGreaterEqual(row['seconds'], 0)
            self.assertEqual(row['source_revision'], 'test-revision')

    def test_no_partial_success(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(folder, SimpleNamespace(state={}), 'test-revision')
            self.assertTrue(runner.record('setup.accounts', lambda: None))
            summary = json.loads((Path(folder) / 'scenarios/e06/summary.json').read_text())
            self.assertEqual(summary['state'], 'failed')

    def test_current_quote_request(self):
        self.assertEqual(quote_request('test-listing', 3, 500000, 'purchase', 'listing'), {
            'subject_id': 'test-listing', 'subject_revision': 3, 'purpose': 'purchase',
            'source': 'listing', 'schedule_id': 'usd-v2', 'currency': 'USD',
            'price_minor': 500000})
        with self.assertRaises(ValueError):
            quote_request('test-listing', True, 500000)

    def test_auction_uses_future_bounded_fixed_end(self):
        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        body = auction_request({'id': 'test-listing'}, now)
        self.assertEqual(body['listing_id'], 'test-listing')
        self.assertEqual(body['opening_minor'], 400000)
        self.assertEqual(body['increment_bands'], [{'from_minor': 0, 'step_minor': 10000}])
        start = datetime.fromisoformat(body['starts_at'])
        end = datetime.fromisoformat(body['ends_at'])
        self.assertGreater(start, now)
        self.assertEqual((end - now).total_seconds(), 25)
        self.assertNotIn('winner', body)

    def test_current_calls_bypass_cached_responses_and_report_replay_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={}, call=Mock(return_value={'state': 'pending'}))
            runner = Runner(folder, walk, 'test-revision')
            runner.record('test-read', lambda: runner.call(
                'orders', 'GET', '/v1/orders/test-order', 'buyer-a', key='test-operation'))
            self.assertFalse(walk.call.call_args.kwargs['durable'])
            self.assertEqual(walk.call.call_args.kwargs['headers'],
                             {'Idempotency-Key': 'test-operation'})
            self.assertEqual(runner.results[0]['operation_ids'], ['test-operation'])

    def test_unknown_response_retains_original_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={}, save=Mock())
            first = Runner(folder, walk, 'test-revision')
            binding = first.bound_request('test-attempt', {'expected_revision': 2, 'route': 'card'})
            key = first.stable_key('test-attempt')
            resumed = Runner(folder, walk, 'test-revision')
            self.assertEqual(resumed.stable_key('test-attempt'), key)
            self.assertEqual(resumed.bound_request('test-attempt',
                {'expected_revision': 3, 'route': 'card'}), binding)

    def test_named_missing_capability_is_private_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(folder, SimpleNamespace(state={}), 'test-revision')
            def unavailable():
                raise MissingCapability('custody.current_receipt_producer')
            self.assertFalse(runner.record('protected_purchase.positive', unavailable))
            self.assertEqual(runner.results[0]['missing_capabilities'],
                             ['custody.current_receipt_producer'])
            with patch('connected_runner.time.monotonic', side_effect=[0, 1]):
                with self.assertRaises(MissingCapability) as error:
                    runner.wait('auction.close_worker', lambda: {'state': 'pending'},
                                lambda row: row['state'] == 'closed', seconds=0.5)
            self.assertEqual(error.exception.names, ['auction.close_worker'])

    def test_auction_uses_returned_winner_order_and_current_quote(self):
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={'listings': [{'id': 'test-listing',
                'facts': {'reference': 'DEMO-WATCH-01'}}]}, save=Mock(),
                quote=Mock(return_value={'id': 'test-quote'}))
            runner = Runner(folder, walk, 'test-revision')
            runner.payment = Mock()
            runner.call = Mock(side_effect=[
                {'status': 'succeeded', 'auction_id': 'test-auction'},
                {'status': 'live', 'revision': 2},
                {'status': 'live', 'revision': 2},
                {'status': 'succeeded'},
                {'won': True, 'order_id': 'test-winner-order', 'closing_minor': 400000},
                {'order': {'total_minor': 412000}, 'quote': {'price_minor': 400000}},
            ])
            runner.auction()
            self.assertEqual(runner.call.call_args_list[3].args[:4],
                ('auction', 'POST', '/v1/auctions/test-auction/bids', 'buyer-a'))
            runner.payment.assert_called_once_with({'winner': 'buyer-a',
                'resource_id': 'test-winner-order', 'quote': {'payable_minor': 412000}})
            self.assertEqual(walk.state['e06_auction']['bid_request'], {
                'amount_minor': 400000, 'fee_quote_id': 'test-quote', 'expected_revision': 2})

    def test_setup_failure_emits_every_required_case_without_success(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(folder, SimpleNamespace(state={}), 'test-revision')
            self.assertEqual(runner.run(False), 1)
            self.assertEqual(len(runner.results), 40)
            self.assertTrue(all(row['state'] == 'failed' for row in runner.results))
            self.assertTrue(all(row['missing_capabilities'] ==
                ['setup.current_signed_in_actors'] for row in runner.results))

    def test_existing_public_file_becomes_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'summary.json'
            path.write_text('{}')
            path.chmod(0o644)
            private_json(path, {'state': 'failed'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_maintenance_request_binds_current_supported_business(self):
        context = dict(actor_id='test-buyer', subject_id='test-buyer',
                       watch_id='test-watch', watch_revision=3)
        destination = dict(organization_id='test-business', brand_id='test-brand',
                           capability_revision=5, policy_revision=2,
                           interventions=['limited_maintenance'])
        body = maintenance_request(context, destination, 'test-operation')
        self.assertEqual(body['watch_revision'], 3)
        self.assertEqual(body['capability_revision'], 5)
        self.assertEqual(body['organization_id'], 'test-business')
        self.assertTrue(body['limited_assessment_permission'])
        self.assertEqual(body['expected_revision'], 0)
        self.assertNotIn('paid', body)
        with self.assertRaises(MissingCapability):
            maintenance_request(context, {**destination, 'interventions': []}, 'test-operation')

    def test_release_request_uses_current_recipient_and_quote(self):
        snapshot = dict(organization_id=None, subject_id='test-order', watch_id='test-watch',
                        quote_id='test-quote', quote_revision=4, policy_revision=2,
                        recipient_id='test-recipient', recipient_revision=3, revision=7)
        body = release_request(snapshot, 'test-buyer', 'test-operation')
        self.assertEqual(body['expected_revision'], 7)
        self.assertEqual(body['recipient_revision'], 3)
        self.assertEqual(body['actor_id'], 'test-buyer')
        self.assertNotIn('state', body)
        result = {**body, 'state': 'paid_out', 'gross_minor': 500000,
                  'fee_minor': 25000, 'net_minor': 475000}
        Runner.verify_release(body, result)
        for changed in ({'net_minor': 500000}, {'recipient_revision': 4}, {'subject_id': 'test-other'}):
            with self.subTest(changed=changed), self.assertRaises(MissingCapability):
                Runner.verify_release(body, {**result, **changed})

    def test_receipt_without_release_prerequisites_cannot_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            reservation = dict(winner='buyer-a', resource_id='test-order',
                               quote={'payable_minor': 515000})
            walk = SimpleNamespace(state={'reservation': reservation})
            runner = Runner(folder, walk, 'test-revision')
            runner.call = Mock(side_effect=[
                {'result': {'buyer_received_at': '2026-11-17T00:00:00Z', 'held': False}},
                {'snapshot': {'subject_id': 'test-order', 'total_minor': 515000},
                 'missing': ['window_open']},
            ])
            with self.assertRaises(MissingCapability) as error:
                runner.downstream('protected_purchase')
            self.assertEqual(error.exception.names, ['release.window_open'])
            self.assertTrue(all(call.args[1] == 'GET' for call in runner.call.call_args_list))

    def test_missing_physical_receipt_does_not_create_handoff(self):
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={'reservation': {
                'winner': 'buyer-a', 'resource_id': 'test-order'}})
            runner = Runner(folder, walk, 'test-revision')
            runner.call = Mock(return_value={'result': None})
            with self.assertRaises(MissingCapability) as error:
                runner.downstream('protected_purchase')
            self.assertEqual(error.exception.names, ['custody.authorized_physical_handoff_producer'])
            runner.call.assert_called_once()

    def test_service_cases_use_connected_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(folder, SimpleNamespace(state={}), 'test-revision')
            runner.connected.fault_case = Mock()
            runner.service_case('duplicate')
            runner.connected.fault_case.assert_called_once_with('service', 'duplicate')

    def test_release_recovery_uses_original_operation_without_new_transfer(self):
        with tempfile.TemporaryDirectory() as folder:
            body = release_request(dict(organization_id=None, subject_id='test-order',
                watch_id='test-watch', quote_id='test-quote', quote_revision=2,
                policy_revision=1, recipient_id='test-seller', recipient_revision=1,
                revision=3), 'test-buyer', 'test-operation')
            receipt = {**body, 'state': 'paid_out', 'gross_minor': 500000,
                       'fee_minor': 25000, 'net_minor': 475000}
            walk = SimpleNamespace(state={'e06_releases': {'protected_purchase': {
                'actor': 'buyer-a', 'request': body, 'result': receipt}}})
            runner = Runner(folder, walk, 'test-revision')
            runner.call = Mock(return_value=receipt)
            runner.release_case('protected_purchase', 'recovery')
            self.assertEqual(runner.call.call_args_list[1].args,
                ('orders', 'POST', '/v1/releases/operations/test-operation/recover', 'buyer-a'))
            self.assertEqual(runner.call.call_args_list[1].kwargs['key'], 'test-operation')

    def test_bid_without_acknowledgment_replays_after_close(self):
        with tempfile.TemporaryDirectory() as folder:
            bid = {'amount_minor': 400000, 'fee_quote_id': 'test-quote',
                   'expected_revision': 2}
            walk = SimpleNamespace(state={
                'listings': [{'id': 'test-listing', 'facts': {'reference': 'DEMO-WATCH-01'}}],
                'e06_auction': {'created': {'auction_id': 'test-auction'},
                                'bid_request': bid},
                'e06_keys': {'auction-bid': 'test-original-operation'}}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            runner.payment = Mock()
            runner.call = Mock(side_effect=[{'status': 'succeeded'},
                {'won': True, 'order_id': 'test-order', 'closing_minor': 400000},
                {'order': {'total_minor': 412000}, 'quote': {'price_minor': 400000}}])
            runner.auction()
            self.assertEqual(runner.call.call_args_list[0].args,
                ('auction', 'POST', '/v1/auctions/test-auction/bids', 'buyer-a', bid))
            self.assertEqual(runner.call.call_args_list[0].kwargs['key'],
                             'test-original-operation')
            runner.payment.assert_called_once()

    def test_release_without_acknowledgment_resolves_original_transfer(self):
        with tempfile.TemporaryDirectory() as folder:
            body = release_request(dict(organization_id=None, subject_id='test-order',
                watch_id='test-watch', quote_id='test-quote', quote_revision=2,
                policy_revision=1, recipient_id='test-seller', recipient_revision=1,
                revision=3), 'test-buyer', 'test-operation')
            receipt = {**body, 'state': 'paid_out', 'gross_minor': 412000,
                       'fee_minor': 12000, 'net_minor': 400000}
            walk = SimpleNamespace(state={'reservation': {'winner': 'buyer-a',
                'resource_id': 'test-order', 'quote': {'payable_minor': 412000}},
                'e06_bindings': {'release:test-order': body}}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            runner.call = Mock(return_value=receipt)
            runner.release('protected_purchase')
            runner.call.assert_called_once_with('orders', 'GET',
                '/v1/releases/operations/test-operation', 'buyer-a', expected=(200, 404))
            self.assertEqual(walk.state['e06_releases']['protected_purchase']['result'], receipt)

    def test_fault_cases_attempt_connected_execution(self):
        for case in ('denied', 'stale', 'cross_business', 'timeout', 'restart',
                     'lost_response', 'duplicate', 'recovery'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                runner = Runner(folder, SimpleNamespace(state={}), 'test-revision')
                runner.connected.fault_case = Mock(return_value=None)
                runner.payment_case('protected_purchase', case)
                runner.connected.fault_case.assert_called_once_with('protected_purchase', case)

    def test_completed_purchase_reconciles_paid_state_and_economics(self):
        cls = load_walkthrough()
        walk = cls.__new__(cls)
        walk.state = {'reservation': {'resource_id': 'test-order', 'winner': 'buyer-a',
            'quote': {'id': 'test-quote', 'payable_minor': 412000}}}
        walk.call = Mock(return_value={'order': {'state': 'paid_held',
            'quote_id': 'test-quote', 'total_minor': 412000}})
        walk.reconcile_phase('purchases')
        self.assertFalse(walk.call.call_args.kwargs['durable'])
        walk.call.return_value['order']['total_minor'] = 1
        with self.assertRaises(MissingCapability):
            walk.reconcile_phase('purchases')

    def test_completed_request_reconciles_submitted_binding(self):
        cls = load_walkthrough()
        walk = cls.__new__(cls)
        walk.state = {'request_draft': {'resource_id': 'test-draft'},
                      'businesses': {'brand': {'id': 'test-brand'}}}
        walk.call = Mock(side_effect=[{'id': 'test-draft', 'kind': 'customization',
            'brand_id': 'test-brand', 'submitted_request_id': 'test-request'},
            {'draft_id': 'test-draft'}])
        walk.reconcile_phase('request')
        self.assertEqual(walk.call.call_args.args[2],
                         '/v1/customization-requests/test-request')

    def test_submission_binds_validated_configuration_and_movement(self):
        draft = {'revision': 3, 'configuration_id': 'test-configuration',
                 'configuration_revision': 4}
        body = submission_request(draft, {'id': 'test-movement', 'revision': 2},
                                  {'status': 'manual_assessment', 'digest': 'test-digest'})
        self.assertEqual(body, {'draft_revision': 3,
            'configuration_id': 'test-configuration', 'configuration_revision': 4,
            'movement_selection_id': 'test-movement', 'movement_revision': 2,
            'expected_digest': 'test-digest'})
        with self.assertRaises(MissingCapability):
            submission_request(draft, {'id': 'test-movement', 'revision': 2},
                               {'status': 'parts_unavailable', 'digest': 'test-digest'})
        self.assertEqual({row[0] for row in sample_options()},
                         {'color', 'material', 'dial', 'sophistication'})

    def test_customization_uses_implemented_submit_and_private_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            draft = {'id': 'test-draft', 'revision': 1, 'brand_id': 'test-brand',
                'kind': 'customization', 'watch_context': 'owned_watch',
                'watch_reference': 'Sample watch', 'scope_intent': 'Sample finish',
                'notes': '', 'options': {}}
            retained = {**draft, 'revision': 2, 'configuration_id': 'test-configuration',
                        'configuration_revision': 4}
            submission = {'id': 'test-operation', 'status': 'succeeded',
                'resource_id': 'test-request', 'request': {'id': 'test-request',
                                                       'draft_id': 'test-draft'}}
            walk = SimpleNamespace(state={'request_draft': {'resource_id': 'test-draft'},
                'businesses': {'brand': {'id': 'test-brand'}}}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            runner.assessment_claim = Mock()
            runner.connected.journey = Mock()
            runner.customization_configuration = Mock(return_value=(
                {'id': 'test-configuration', 'revision': 4},
                {'id': 'test-movement', 'revision': 1}))
            runner.call = Mock(side_effect=[draft, {}, retained,
                {'status': 'manual_assessment', 'digest': 'test-digest'},
                submission, submission, submission['request'], {}])
            runner.customization()
            runner.connected.journey.assert_called_once_with('customization')
            self.assertEqual(runner.call.call_args_list[4].args[2],
                             '/v1/request-drafts/test-draft/submit')
            self.assertEqual(runner.call.call_args_list[5].args[2],
                             '/v1/customization-operations/test-operation')
            self.assertEqual(walk.state['e06_customization']['submission'], submission)

    def test_submitted_draft_recovers_original_receipt_after_lost_response(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                body = {'draft_revision': 2, 'expected_digest': 'test-digest'}
                receipt = {'id': 'test-receipt', 'status': 'succeeded',
                    'resource_id': 'test-request',
                    'request': {'id': 'test-request', 'draft_id': 'test-draft'}}
                walk = SimpleNamespace(state={'request_draft': {'resource_id': 'test-draft'},
                    'businesses': {'brand': {'id': 'test-brand'}},
                    'e06_bindings': {'customization-submit': body},
                    'e06_keys': {'customization-submit': 'test-original-operation'}}, save=Mock())
                runner = Runner(folder, walk, 'test-revision')
                runner.assessment_claim = Mock()
                runner.connected.journey = Mock()
                runner.call = Mock(side_effect=[{'submitted_request_id': 'test-request'},
                    receipt, {**receipt, 'resource_id': 'test-other'} if changed else receipt,
                    receipt['request'], {}])
                if changed:
                    with self.assertRaises(MissingCapability):
                        runner.customization()
                    self.assertNotIn('submission', walk.state['e06_customization'])
                else:
                    runner.customization()
                    self.assertEqual(walk.state['e06_customization']['submission'], receipt)
                    runner.connected.journey.assert_called_once_with('customization')
                replay = runner.call.call_args_list[1]
                self.assertEqual(replay.args, ('catalog', 'POST',
                    '/v1/request-drafts/test-draft/submit', 'buyer-a', body))
                self.assertEqual(replay.kwargs['key'], 'test-original-operation')

    def test_assessment_claim_binds_current_assignment_and_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            walk = SimpleNamespace(state={}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            context = dict(current_watch_id='test-watch', actor_id='test-actor',
                revision=0, current_request_revision=2, assignment_revision=0,
                current_capability_revision=3)
            def respond(service, method, route, actor, body=None, **kwargs):
                if method == 'POST':
                    return {**body, 'state': 'claimed', 'claimant': 'test-actor',
                            'revision': 1, 'assignment_revision': 1}
                binding = walk.state['e06_bindings']['assessment-claim:test-request']
                return {**binding, 'state': 'claimed', 'claimant': 'test-actor',
                        'revision': 1, 'assignment_revision': 1}
            runner.call = Mock(side_effect=respond)
            runner.assessment_claim('test-request', 'test-business', context)
            first = runner.call.call_args_list[0]
            self.assertEqual(first.args[4]['request_revision'], 2)
            self.assertEqual(first.args[4]['capability_revision'], 3)
            runner.assessment_claim('test-request', 'test-business',
                                    {**context, 'revision': 1})
            self.assertEqual(first, runner.call.call_args_list[2])

    def test_customization_cases_use_connected_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(folder, SimpleNamespace(state={}), 'test-revision')
            runner.connected.fault_case = Mock()
            runner.customization_case('cross_account')
            runner.connected.fault_case.assert_called_once_with('customization', 'cross_account')

    def test_lost_payment_reply_reconciles_before_exact_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            binding = {'expected_revision': 8, 'route': 'card', 'quote_revision': 3,
                       'total_minor': 412000, 'currency': 'USD'}
            checkout = {'order': {'state': 'paid_held'}, 'quote': {'revision': 3},
                        'attempts': [{'id': 'test-attempt'}]}
            walk = SimpleNamespace(state={'reservation': {'winner': 'buyer-a',
                'resource_id': 'test-order'}, 'e06_bindings': {
                    'attempt:test-order': binding}}, save=Mock())
            runner = Runner(folder, walk, 'test-revision')
            runner.call = Mock(side_effect=[checkout, None, checkout,
                {'status': 'succeeded', 'attempt': {'id': 'test-attempt'}}, checkout])
            runner.lost_payment_response('protected_purchase')
            first, replay = runner.call.call_args_list[1], runner.call.call_args_list[3]
            self.assertEqual(first, replay)
            self.assertEqual(runner.call.call_args_list[2].args[1], 'GET')

    def test_release_conditions_cannot_expose_unrecognized_response_content(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(folder, SimpleNamespace(state={'reservation': {
                'winner': 'buyer-a', 'resource_id': 'test-order',
                'quote': {'payable_minor': 515000}}}), 'test-revision')
            runner.call = Mock(return_value={'snapshot': {
                'subject_id': 'test-order', 'total_minor': 515000},
                'missing': ['test-private-response']})
            with self.assertRaises(MissingCapability) as error:
                runner.release('protected_purchase')
            self.assertEqual(error.exception.names, ['release.invalid_condition_response'])


if __name__ == '__main__':
    unittest.main()
