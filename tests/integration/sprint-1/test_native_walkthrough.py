"""Bounded native command contracts; no connected execution."""
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

spec = importlib.util.spec_from_file_location(
    'connected_walkthrough', Path(__file__).with_name('connected_walkthrough.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeWalkthroughTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.run = Path(self.folder.name)
        (self.run / 'domain-contracts/bt_contracts').mkdir(parents=True)
        self.config = self.run / 'native-v1.json'
        self.config.write_text(json.dumps({'schema_version': 1, 'services': {
            name: {'env': {'BT_DATABASE_URL': 'private-database',
                           'CATALOG_URL': 'catalog-provider', 'PRICING_URL': 'pricing-provider'}}
            for name in ('catalog', 'identity')}}))
        self.config.chmod(0o600)
        for target in ('socket.socket.connect', 'subprocess.Popen'):
            guard = patch(target, side_effect=AssertionError('Unexpected external operation'))
            guard.start()
            self.addCleanup(guard.stop)
        self.client = Mock()
        self.client.request.side_effect = AssertionError('Unexpected HTTP request')
        client_patch = patch.object(module.httpx, 'Client', return_value=self.client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        self.walk = module.Walkthrough('http://example.test', 'native', self.run)
        self.walk.state = {'accounts': {
            name: {'access_token': name + '-private-token'} for name in ('seller', 'dealer', 'brand')},
            'businesses': {'dealer': {'id': 'business-reference'}, 'brand': {'id': 'brand-reference'}}}

    def test_reviewed_stock_media_request_survives_gateway_and_refresh(self):
        for actor, listing_key in (('seller', 'DEMO-WATCH-01'),
                                   ('dealer', 'DEMO-WATCH-02'), ('brand', 'DEMO-WATCH-06')):
            with self.subTest(actor=actor):
                root = self.run / actor
                (root / 'demo').mkdir(parents=True)
                (root / 'web/public/demo/watches').mkdir(parents=True)
                asset = 'fixture asset&1'
                content = b'fixture-image-bytes'
                (root / 'web/public/demo/watches/fixture.jpg').write_bytes(content)
                (root / 'demo/images-manifest.json').write_text(json.dumps({'assets': [
                    {'id': asset, 'file': 'fixture.jpg'}]}))
                (root / 'demo/listings.json').write_text(json.dumps({'listings': [{
                    'id': listing_key, 'seller_type': 'private' if actor == 'seller' else 'dealer',
                    'brand': 'Fixture', 'model': 'Fixture', 'condition': 'Fixture condition',
                    'location': 'Beirut', 'sale_mode': 'fixed-price', 'price_minor': 100,
                    'image_ids': [asset]}]}))
                row = {'id': 'fixture-listing', 'status': 'draft', 'revision': 7, 'photo_ids': [], 'facts': {'price_minor': 100}}
                self.walk.state['accounts'][actor]['refresh_cookie'] = 'test-refresh-cookie'
                refreshed = {'access_token': 'test-refreshed-token'}
                self.client.cookies.get.return_value = 'test-refresh-cookie'
                self.client.request.side_effect = [
                    module.httpx.Response(401),
                    module.httpx.Response(201, json={'listing': {**row, 'revision': 8}})]
                original_call = self.walk.call
                def command(service, method, route, *args, **kwargs):
                    if service == 'pricing':
                        raise StopIteration
                    if route.endswith('/refresh'):
                        return refreshed
                    if '/media?' in route:
                        return original_call(service, method, route, *args, **kwargs)
                    return row
                with patch.object(module, 'ROOT', root), patch.object(self.walk, 'login'), \
                        patch.object(self.walk, 'call', side_effect=command):
                    with self.assertRaises(StopIteration):
                        self.walk.prepare_reviewed_stock()
                first, retry = self.client.request.call_args_list[-2:]
                self.assertEqual(first.args[:1], ('POST',))
                route, query = first.args[1].split('?')
                self.assertEqual(route, '/api/web/v1/catalog/v1/seller/listings/fixture-listing/media')
                expected = {'kind': ['public_photo'], 'public_safe': ['true'], 'demo_asset': [asset]}
                if actor != 'seller':
                    expected['organization_id'] = [self.walk.state['businesses'][actor]['id']]
                self.assertEqual(parse_qs(query), expected)
                self.assertEqual(first.kwargs['content'], content)
                self.assertIsNone(first.kwargs['json'])
                # These are the headers the gateway forwards to catalog.
                forwarded = {key: value for key, value in retry.kwargs['headers'].items()
                             if key in ('Authorization', 'Content-Type', 'Idempotency-Key', 'If-Match')}
                self.assertEqual(forwarded, retry.kwargs['headers'])
                self.assertEqual(forwarded['Content-Type'], 'application/octet-stream')
                self.assertEqual(forwarded['If-Match'], '7')
                self.assertTrue(forwarded['Idempotency-Key'])
                self.assertEqual(first.kwargs['headers']['Idempotency-Key'], forwarded['Idempotency-Key'])
                self.assertEqual(forwarded['Authorization'], 'Bearer test-refreshed-token')
                self.assertEqual(retry.args, first.args)
                self.assertEqual(retry.kwargs['content'], content)

    def test_publication_plan_and_real_result_checks(self):
        rows = [{'id': str(number), 'is_demo': True, 'status': 'published'}
                for number in range(6)]
        with patch.object(self.walk, 'login'), patch.object(self.walk, 'call', side_effect=[
            {'items': rows[:3]}, {'items': rows[3:5]}, {'items': rows[5:]}, {'items': [{'demo': True}]}]), \
                patch.object(self.walk, 'prepare_reviewed_stock') as prepare:
            self.walk.publication()
        prepare.assert_called_once()
        self.assertEqual(self.walk.state['listings'], rows)
        self.assertEqual(stat.S_IMODE(self.walk.path.stat().st_mode), 0o600)
        self.assertNotIn('private-token', json.dumps(self.walk.evidence))

    def test_incomplete_publication_is_rejected(self):
        with patch.object(self.walk, 'login'), patch.object(self.walk, 'call', return_value={'items': []}), \
                patch.object(self.walk, 'prepare_reviewed_stock'):
            with self.assertRaises(AssertionError):
                self.walk.publication()

    def test_bootstrap_fresh_login_and_checkpoint(self):
        events = []
        def login(name):
            self.assertNotIn('operator', self.walk.state['accounts'])
            events.append(name)
            self.walk.state['accounts'][name] = {'principal': {
                'permissions': [] if len(events) == 1 else ['identity.businesses.manage']}}
        with patch.object(self.walk, 'login', side_effect=login), \
                patch.object(module.subprocess, 'run', return_value=Mock(returncode=0)) as process:
            self.walk.bootstrap()
            self.walk.bootstrap()
        self.assertEqual(events, ['operator', 'operator', 'operator'])
        process.assert_called_once()
        command = process.call_args.args[0]
        self.assertEqual(command[1:3], ['-m', 'service_app.bootstrap_operator'])
        self.assertNotIn('docker', command)
        self.assertEqual(process.call_args.kwargs['cwd'], self.run)
        self.assertEqual(self.client.cookies.clear.call_count, 3)

    def test_failure_redacts_output_and_does_not_seal(self):
        with patch.object(self.walk, 'login', side_effect=self.unprivileged_login), \
                patch.object(module.subprocess, 'run', return_value=Mock(
                returncode=1, stdout='private-token', stderr='private-database')):
            with self.assertRaisesRegex(RuntimeError, '^Local command failed;') as caught:
                self.walk.bootstrap()
        self.assertNotIn('private-', str(caught.exception))
        self.assertNotIn('operator_bootstrapped', self.walk.state)
        self.assertEqual(self.walk.evidence, [{'transport': 'native', 'status': 1}])

    def unprivileged_login(self, name):
        self.walk.state['accounts'][name] = {'principal': {'permissions': []}}

    def test_timeout_is_redacted_and_pending_retry_does_not_execute(self):
        with patch.object(self.walk, 'login', side_effect=self.unprivileged_login), \
                patch.object(module.subprocess, 'run', side_effect=module.subprocess.TimeoutExpired(
                    ['private-command'], 120, output='private-token', stderr='private-database')) as process:
            with self.assertRaisesRegex(RuntimeError, '^Local command timed out;') as caught:
                self.walk.bootstrap()
            self.assertEqual(process.call_args.kwargs['timeout'], 120)
            self.assertNotIn('private-', str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(json.loads(self.walk.path.read_text())['operator_bootstrap_pending'])
            with self.assertRaisesRegex(RuntimeError, 'unresolved'):
                self.walk.bootstrap()
            process.assert_called_once()
        self.assertEqual(self.walk.evidence, [{'transport': 'native', 'status': 'timeout'}])

    def test_committed_command_without_checkpoint_reconciles_current_authority(self):
        for pending in (False, True):
            self.walk.state.pop('operator_bootstrapped', None)
            self.walk.state['operator_bootstrap_pending'] = pending
            def login(name):
                self.assertNotIn(name, self.walk.state['accounts'])
                self.walk.state['accounts'][name] = {'principal': {
                    'permissions': ['identity.businesses.manage']}}
            with patch.object(self.walk, 'login', side_effect=login), \
                    patch.object(module.subprocess, 'run') as process:
                self.walk.bootstrap()
            process.assert_not_called()
            self.assertTrue(self.walk.state['operator_bootstrapped'])
            self.assertNotIn('operator_bootstrap_pending', self.walk.state)

    def test_checkpoint_failure_retains_pending_for_authority_reconciliation(self):
        events = []
        def login(name):
            events.append(name)
            self.walk.state['accounts'][name] = {'principal': {
                'permissions': [] if len(events) == 1 else ['identity.businesses.manage']}}
        save = self.walk.save
        def save_until_committed():
            if self.walk.state.get('operator_bootstrapped'):
                raise OSError('Checkpoint unavailable')
            save()
        with patch.object(self.walk, 'login', side_effect=login), \
                patch.object(self.walk, 'save', side_effect=save_until_committed), \
                patch.object(module.subprocess, 'run', return_value=Mock(returncode=0)) as process:
            with self.assertRaises(OSError):
                self.walk.bootstrap()
        self.walk.state = json.loads(self.walk.path.read_text())
        self.assertTrue(self.walk.state['operator_bootstrap_pending'])
        with patch.object(self.walk, 'login', side_effect=login), \
                patch.object(module.subprocess, 'run') as retry:
            self.walk.bootstrap()
        process.assert_called_once()
        retry.assert_not_called()

    def test_proposed_competition_contract_not_provider_compatibility(self):
        # Local expectations only; current provider equal-ceiling revision is deferred.
        self.walk.state['auctions'] = {'DEMO-WATCH-01': {'auction_id': 'lot'}}
        prices = [10000, 11000, 12000, 16000, 20000, 20000]
        leaders = ['buyer-a', 'buyer-b', 'buyer-a', 'buyer-a', 'buyer-b', 'buyer-b']
        for wrong_leader, extra_bid in ((False, False), (True, False), (False, True)):
            index = -1
            def call(service, method, route, actor=None, body=None):
                nonlocal index
                if route.endswith('/history'):
                    return {'items': [{'amount_minor': 20000}] if extra_bid and index == 5 else [],
                            'has_more': False}
                if method == 'POST':
                    index += 1
                    return {'status': 'succeeded'}
                if route == '/v1/my-bids':
                    if index == 0 and actor == 'buyer-b':
                        return {'items': []}
                    leading = actor == leaders[index]
                    if wrong_leader and index == 4:
                        leading = not leading
                    return {'items': [{'auction_id': 'lot',
                                       'my_status': 'leading' if leading else 'outbid'}]}
                return {'revision': 1, 'current_minor': prices[max(index, 0)]}
            with patch.object(self.walk, 'login'), patch.object(self.walk, 'wait_for_live'), \
                    patch.object(self.walk, 'quote', return_value={'id': 'quote'}), \
                    patch.object(self.walk, 'call', side_effect=call):
                if wrong_leader or extra_bid:
                    with self.assertRaises(AssertionError):
                        self.walk.bids()
                else:
                    self.walk.bids()

    def test_main_closes_client_on_timeout_and_evidence_write_failure(self):
        for write_failure in (False, True):
            self.client.close.reset_mock()
            def timeout():
                self.walk.execute(['private-command'], {})
            with patch.object(module, 'Walkthrough', return_value=self.walk), \
                    patch.object(module.sys, 'argv', ['walkthrough', 'all', '--backend',
                                                     'native', '--run-dir', str(self.run)]), \
                    patch.object(self.walk, 'all', side_effect=timeout), \
                    patch.object(module.subprocess, 'run', side_effect=module.subprocess.TimeoutExpired(
                        ['private-command'], 120, output='private-token')):
                if write_failure:
                    with patch.object(Path, 'write_text', side_effect=OSError('Evidence unavailable')):
                        with self.assertRaises(OSError):
                            module.main()
                else:
                    with self.assertRaisesRegex(RuntimeError, 'timed out'):
                        module.main()
                    evidence = (self.run / 'all-evidence.json').read_text()
                    self.assertNotIn('private-', evidence)
                    self.assertIn('timeout', evidence)
            self.client.close.assert_called_once()

    def test_pending_mutations_reuse_exact_command_after_restart(self):
        for service, route in (('auction', '/v1/auctions/lot/bids'),
                               ('orders', '/v1/reservations')):
            with self.subTest(service=service):
                self.walk.state = {'accounts': {'buyer-a': {'access_token': 'private-token'}}}
                self.walk.phase = 'bids' if service == 'auction' else 'purchases'
                self.walk.positions = {}
                self.client.request.side_effect = TimeoutError('Uncertain response')
                original = {'expected_revision': 1, 'quote_id': 'retained-quote'}
                with self.assertRaises(TimeoutError):
                    self.walk.call(service, 'POST', route, 'buyer-a', original)
                first = self.client.request.call_args.kwargs
                resumed = module.Walkthrough('http://example.test', 'native', self.run)
                resumed.phase = self.walk.phase
                response = Mock(status_code=200, headers={})
                response.json.return_value = {'status': 'succeeded'}
                self.client.request.side_effect = None
                self.client.request.return_value = response
                resumed.call(service, 'POST', route, 'buyer-a', {'expected_revision': 99})
                retry = self.client.request.call_args.kwargs
                self.assertEqual(first['headers']['Idempotency-Key'],
                                 retry['headers']['Idempotency-Key'])
                self.assertEqual(retry['json'], original)
                resumed.positions = {}
                self.client.request.reset_mock()
                self.assertEqual(resumed.call(service, 'POST', route, 'buyer-a'),
                                 {'status': 'succeeded'})
                self.client.request.assert_not_called()
                self.assertEqual(stat.S_IMODE(resumed.path.stat().st_mode), 0o600)
                self.assertNotIn('private-token', json.dumps(resumed.evidence))

    def test_auction_phase_resumes_second_watch_without_aliasing_first(self):
        self.walk.state = {'accounts': {'seller': {'access_token': 'private-token'}},
                           'businesses': {'dealer': {'id': 'business'}},
                           'listings': [{'id': reference, 'facts': {'reference': reference}}
                                        for reference in ('DEMO-WATCH-01', 'DEMO-WATCH-03')]}
        def accepted(identifier):
            response = Mock(status_code=200, headers={})
            response.json.return_value = {'status': 'succeeded', 'auction_id': identifier}
            return response
        self.client.request.side_effect = [accepted('first'), TimeoutError()]
        with patch.object(self.walk, 'login'):
            with self.assertRaises(TimeoutError):
                self.walk.run_phase('auctions')
        pending = self.client.request.call_args.kwargs
        resumed = module.Walkthrough('http://example.test', 'native', self.run)
        self.client.request.side_effect = [accepted('second')]
        with patch.object(resumed, 'login'):
            resumed.run_phase('auctions')
        retried = self.client.request.call_args.kwargs
        self.assertEqual(pending['json'], retried['json'])
        self.assertEqual(pending['headers'], retried['headers'])
        self.assertEqual(resumed.state['auctions']['DEMO-WATCH-01']['auction_id'], 'first')
        self.assertEqual(resumed.state['auctions']['DEMO-WATCH-03']['auction_id'], 'second')

    def test_live_poll_reads_current_state_after_interruption(self):
        self.walk.phase = 'bids'
        scheduled = Mock(status_code=200, headers={})
        scheduled.json.return_value = {'status': 'scheduled'}
        live = Mock(status_code=200, headers={})
        live.json.return_value = {'status': 'live'}
        self.client.request.side_effect = [scheduled, TimeoutError()]
        with patch.object(module.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                self.walk.wait_for_live('lot')
        self.client.request.side_effect = [live]
        self.walk.wait_for_live('lot')
        self.assertNotIn('call_journal', self.walk.state)

    def test_completed_bootstrap_rechecks_revoked_authority(self):
        self.walk.state['completed_phases'] = ['bootstrap']
        self.walk.state['operator_bootstrapped'] = True
        with patch.object(self.walk, 'login', side_effect=self.unprivileged_login), \
                patch.object(module.subprocess, 'run') as process:
            with self.assertRaisesRegex(RuntimeError, 'unresolved'):
                self.walk.run_phase('bootstrap')
        process.assert_not_called()

    def test_completed_phase_without_current_reads_is_incomplete(self):
        self.walk.state['completed_phases'] = ['request']
        with patch.object(self.walk, 'login'), patch.object(self.walk, 'request'):
            with self.assertRaisesRegex(RuntimeError, 'reconciliation unavailable'):
                self.walk.run_phase('request')

    def test_completed_publication_checks_current_stock_without_import(self):
        self.walk.state['completed_phases'] = ['publication']
        response = Mock(status_code=200, headers={})
        response.json.return_value = {'items': []}
        self.client.request.side_effect = None
        self.client.request.return_value = response
        def login(name):
            self.walk.state['accounts'][name] = {'access_token': name + '-private-token'}
        with patch.object(self.walk, 'login', side_effect=login), \
                patch.object(module.subprocess, 'run') as process:
            with self.assertRaises(AssertionError):
                self.walk.run_phase('publication')
        process.assert_not_called()
        self.assertEqual(self.client.request.call_count, 3)

    def test_verification_reads_ignore_old_journal_and_check_access(self):
        self.walk.phase = 'publication'
        route = '/v1/seller/listings'
        key = json.dumps(['publication', 'catalog', 'GET', route, 'seller', 0])
        self.walk.state['call_journal'] = {key: {
            'response': {'items': [{'status': 'published'}]}, 'status': 200}}
        response = Mock(status_code=403, headers={})
        self.client.request.side_effect = None
        self.client.request.return_value = response
        with self.assertRaises(AssertionError):
            self.walk.call('catalog', 'GET', route, 'seller')
        self.client.request.assert_called_once()
        self.assertEqual(self.walk.state['call_journal'][key]['status'], 200)

    def test_completed_contacts_reject_current_unverified_state(self):
        self.walk.state['completed_phases'] = ['contacts']
        with patch.object(self.walk, 'login'), patch.object(
                self.walk, 'call', return_value={'email_verified': False}) as call:
            with self.assertRaisesRegex(RuntimeError, 'Current contact unverified'):
                self.walk.run_phase('contacts')
        call.assert_called_once_with('identity', 'GET', '/v1/contacts', 'seller')

    def test_completed_phase_cannot_introduce_mutation(self):
        self.walk.phase = 'directory'
        self.walk.reconciling = True
        with self.assertRaisesRegex(RuntimeError, 'Unrecorded mutation'):
            self.walk.call('service-operations', 'POST', '/v1/directory/choices')
        self.client.request.assert_not_called()

    def test_bid_phase_recovers_lost_second_response(self):
        self.walk.state['auctions'] = {'DEMO-WATCH-01': {'auction_id': 'lot'}}
        prices = [10000, 11000, 12000, 16000, 20000, 20000]
        leaders = ['buyer-a', 'buyer-b', 'buyer-a', 'buyer-a', 'buyer-b', 'buyer-b']
        committed = {}
        index = -1
        lost = False
        uncertain = None

        def request(method, route, **kwargs):
            nonlocal index, lost, uncertain
            if method == 'POST':
                key = kwargs['headers']['Idempotency-Key']
                if key not in committed:
                    index += 1
                    committed[key] = dict(kwargs['json'])
                    if index == 1 and not lost:
                        lost = True
                        uncertain = (key, dict(kwargs['json']))
                        raise TimeoutError('Response unavailable')
                else:
                    self.assertEqual(kwargs['json'], committed[key])
                result = {'status': 'succeeded'}
            elif route.endswith('/history'):
                result = {'items': [], 'has_more': False}
            elif route.endswith('/my-bids'):
                actor = kwargs['headers']['Authorization'].split()[-1]
                result = {'items': [{'auction_id': 'lot', 'my_status':
                          'leading' if actor == leaders[index] else 'outbid'}]}
            else:
                result = {'revision': index + 2, 'current_minor': prices[max(index, 0)]}
            response = Mock(status_code=200, headers={})
            response.json.return_value = result
            return response

        def login(name):
            self.walk.state['accounts'][name] = {'access_token': name}

        self.client.request.side_effect = request
        with patch.object(self.walk, 'login', side_effect=login), \
                patch.object(self.walk, 'wait_for_live'), \
                patch.object(self.walk, 'quote', return_value={'id': 'quote'}):
            with self.assertRaises(TimeoutError):
                self.walk.run_phase('bids')
        resumed = module.Walkthrough('http://example.test', 'native', self.run)
        self.walk = resumed
        with patch.object(resumed, 'login', side_effect=login), \
                patch.object(resumed, 'wait_for_live'), \
                patch.object(resumed, 'quote', return_value={'id': 'new-quote'}):
            resumed.run_phase('bids')
        self.assertEqual(len(committed), 6)
        self.assertEqual(committed[uncertain[0]], uncertain[1])
        self.assertIn('bids', resumed.state['completed_phases'])
        self.assertEqual(index, 5)

    def test_all_rechecks_completed_onboarding_before_pending_phase(self):
        self.walk.state.update({
            'completed_phases': ['accounts', 'bootstrap', 'onboard'],
            'businesses': {kind: {'id': kind} for kind in ('dealer', 'brand')},
            'application': {'id': 'application'}})
        self.walk.state['accounts'] = {name: {} for name in module.ACCOUNTS}
        permissions = ['identity.businesses.manage']
        capabilities = ['business.stock.write', 'business.jobs.write',
                        'business.records.read', 'business.staff.manage']

        def login(name):
            result = {'account': {'id': name}, 'principal': {'permissions': permissions}}
            self.walk.state['accounts'][name] = result
            return result

        def call(service, method, route, actor=None):
            self.assertEqual(method, 'GET')
            if route.endswith('/memberships'):
                kind = route.split('/')[-2]
                return {'items': [{'subject_id': name, 'state': 'active',
                                   'capabilities': capabilities}
                                  for name in [kind] + (['colleague'] if kind == 'dealer' else [])]}
            if route.endswith('/applications/me'):
                return {'application': {'id': 'application', 'status': 'approved'}}
            return {'kind': route.split('/')[-1], 'state': 'active'}

        with patch.object(self.walk, 'login', side_effect=login), \
                patch.object(self.walk, 'call', side_effect=call) as reads, \
                patch.object(self.walk, 'contacts', side_effect=TimeoutError('Pending contact')) as pending:
            with self.assertRaises(TimeoutError):
                self.walk.all()
        pending.assert_called_once()
        self.assertEqual(reads.call_count, 5)
        self.assertNotIn('contacts', self.walk.state['completed_phases'])
        permissions.clear()
        with patch.object(self.walk, 'login', side_effect=login), \
                patch.object(self.walk, 'call', side_effect=call), \
                patch.object(self.walk, 'contacts') as pending:
            with self.assertRaises(AssertionError):
                self.walk.run_phase('onboard')
        pending.assert_not_called()

    def test_authority_rejection_renews_named_actor_and_retries_once(self):
        for refresh_cookie in (None, 'seller-refresh'):
            for retry_status in (200, 401):
                with self.subTest(refresh_cookie=bool(refresh_cookie), retry_status=retry_status):
                    self.walk.state = {'accounts': {
                        'seller': {'access_token': 'old-token', 'refresh_cookie': refresh_cookie},
                        'dealer': {'access_token': 'dealer-token'}}}
                    self.walk.evidence = []
                    self.client.cookies.clear.reset_mock()
                    self.client.cookies.set.reset_mock()
                    self.client.cookies.get.return_value = 'renewed-refresh'
                    calls = []
                    renewed = {'access_token': 'new-token', 'account': {'id': 'seller'}}

                    def request(method, route, **kwargs):
                        calls.append((method, route, {**kwargs, 'headers': dict(kwargs['headers'])}))
                        status = 401 if len(calls) == 1 else 200 if len(calls) == 2 else retry_status
                        response = Mock(status_code=status, headers={})
                        response.json.return_value = dict(renewed) if len(calls) == 2 else {'email_verified': True}
                        return response

                    self.client.request.side_effect = request
                    if retry_status == 401:
                        with self.assertRaises(AssertionError):
                            self.walk.call('identity', 'GET', '/v1/contacts', 'seller')
                    else:
                        self.assertEqual(self.walk.call('identity', 'GET', '/v1/contacts', 'seller'),
                                         {'email_verified': True})
                    self.assertEqual(len(calls), 3)
                    endpoint = 'refresh' if refresh_cookie else 'login'
                    self.assertEqual(calls[1][:2], ('POST', '/api/web/v1/identity/v1/accounts/' + endpoint))
                    self.assertNotIn('Authorization', calls[1][2]['headers'])
                    self.assertEqual(calls[1][2]['json'], None if refresh_cookie else {
                        'email': 'seller.s1@example.test', 'password': module.PASSWORD})
                    self.client.cookies.clear.assert_called_once_with()
                    if refresh_cookie:
                        self.client.cookies.set.assert_called_once_with('bt_refresh', refresh_cookie)
                    else:
                        self.client.cookies.set.assert_not_called()
                    self.assertEqual(calls[2][:2], calls[0][:2])
                    original, retried = calls[0][2], calls[2][2]
                    self.assertEqual(original['headers']['Authorization'], 'Bearer old-token')
                    self.assertEqual(retried['headers']['Authorization'], 'Bearer new-token')
                    original['headers']['Authorization'] = retried['headers']['Authorization']
                    self.assertEqual(retried, original)
                    self.assertEqual(self.walk.state['accounts']['seller']['access_token'], 'new-token')
                    self.assertEqual(self.walk.state['accounts']['seller']['refresh_cookie'], 'renewed-refresh')
                    self.assertEqual(self.walk.state['accounts']['dealer']['access_token'], 'dealer-token')
                    self.assertEqual(json.loads(self.walk.path.read_text())['accounts'], self.walk.state['accounts'])
                    self.assertEqual([row['status'] for row in self.walk.evidence], [401, 200, retry_status])

    def test_unauthenticated_rejection_is_not_retried(self):
        self.client.request.side_effect = None
        self.client.request.return_value = Mock(status_code=401, headers={})
        with self.assertRaises(AssertionError):
            self.walk.call('identity', 'GET', '/v1/contacts')
        self.client.request.assert_called_once()
        self.client.cookies.clear.assert_not_called()

    def test_order(self):
        phases = ['accounts', 'bootstrap', 'onboard', 'contacts', 'publication',
                  'auctions', 'bids', 'purchases', 'directory', 'request']
        calls = []
        for phase in phases:
            setattr(self.walk, phase, lambda phase=phase: calls.append(phase))
        self.walk.all()
        self.assertEqual(calls, phases)

    def test_private_configuration_and_required_directory(self):
        with self.assertRaises(ValueError):
            module.Walkthrough('http://example.test', 'native')
        self.config.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private'):
            self.walk.native_plan('identity', ['service_app.bootstrap_operator'])

    def test_existing_state_must_be_private(self):
        self.walk.path.write_text('{}')
        self.walk.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private'):
            module.Walkthrough('http://example.test', 'native', self.run)

    def test_authoritative_live_poll_is_bounded(self):
        with patch.object(self.walk, 'call', side_effect=[
                {'status': 'scheduled'}, {'status': 'live'}]) as call, \
                patch.object(module.time, 'sleep') as sleep:
            self.walk.wait_for_live('auction-reference')
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(1)
        with patch.object(self.walk, 'call', return_value={'status': 'scheduled'}) as call, \
                patch.object(module.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                self.walk.wait_for_live('auction-reference')
        self.assertEqual(call.call_count, 10)
        self.assertEqual(sleep.call_count, 9)
        with patch.object(self.walk, 'call', return_value={'status': 'ended'}), \
                patch.object(module.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'not live'):
                self.walk.wait_for_live('auction-reference')
        sleep.assert_not_called()

    def test_container_default(self):
        walk = module.Walkthrough('http://example.test', run_dir=self.run)
        self.assertEqual(walk.backend, 'container')


if __name__ == '__main__':
    unittest.main()


class ListingReviewWalkthroughTests(unittest.TestCase):
    setUp = NativeWalkthroughTests.setUp

    def test_private_proofs_precede_publication_and_businesses_publish(self):
        self.walk.state['accounts']['operator'] = {'account': {'id': 'test-reviewer'}}
        rows, calls = {}, []

        def call(service, method, route, actor=None, body=None, **kwargs):
            calls.append((service, method, route, actor, body))
            path = route.split('?')[0]
            if service == 'pricing':
                return {'id': 'test-quote', 'schedule_id': 'usd-v2'}
            if service == 'identity':
                if path.endswith('/challenges'):
                    return {'revision': 1, 'challenge_id': 'test-challenge', 'code': '123456'}
                if path.endswith('/submissions'):
                    assert actor == 'seller' and body['photo_base64']
                    return {'revision': 2}
                if path.endswith('/assignment'):
                    assert actor == 'operator' and body['reviewer_id'] == 'test-reviewer'
                    return {'revision': 3, 'assignment_revision': 1}
                assert actor == 'operator' and body['verdict'] == 'approved'
                return {'revision': 4}
            if path == '/v1/seller/listings':
                assert body['facts']['sale_mode'] in {'auction', 'fixed_price'}
                identifier = body['demo_key']
                rows[identifier] = dict(id=identifier, revision=1, status='draft', photo_ids=[], facts=body['facts'])
                return rows[identifier]
            identifier = path.split('/')[4]
            row = rows[identifier]
            if method == 'GET':
                return row
            if path.endswith('/media'):
                row['photo_ids'] = ['test-photo']
                return {'listing': row}
            if kwargs.get('expected') == (503,):
                return {'error': {'code': 'publication_review_pending'}}
            row['status'] = 'published'
            return row

        with patch.object(self.walk, 'login'), patch.object(self.walk, 'call', side_effect=call):
            self.walk.prepare_reviewed_stock()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row['status'] == 'published' for row in rows.values()))
        self.assertEqual(sum(route.endswith('/decision') for _, _, route, _, _ in calls), 3)
        self.assertTrue(any(actor == 'brand' and '/publish?' in route for _, _, route, actor, _ in calls))
