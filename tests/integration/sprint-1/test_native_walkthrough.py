"""Bounded native command contracts; no connected execution."""
import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

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
            name: {'access_token': name + '-private-token'} for name in ('seller', 'dealer')},
            'businesses': {'dealer': {'id': 'business-reference'}}}


    def test_publication_plan_and_real_result_checks(self):
        private = {'DEMO-WATCH-01', 'DEMO-WATCH-03', 'DEMO-WATCH-05'}
        references = [*sorted(private), 'DEMO-WATCH-02', 'DEMO-WATCH-04', 'DEMO-WATCH-06']
        rows = [{'id': str(number), 'is_demo': True, 'status': 'published', 'revision': 3,
                 'physical_watch_id': f'watch-{number}', 'facts': {'reference': ref},
                 'seller_type': 'private' if ref in private else 'dealer'}
                for number, ref in enumerate(references)]
        self.walk.state['listing_proofs'] = {row['facts']['reference']: {
            'binding': {'id': row['id'], 'watch_id': row['physical_watch_id'], 'revision': 2},
            'commands': {'decide': {'result': {'state': 'approved'}}},
        } for row in rows[:3]}
        with patch.object(self.walk, 'login'), patch.object(self.walk, 'call', side_effect=[
            {'items': rows[:3]}, {'items': rows[3:]}, {'items': [{'demo': True}]}]), \
                patch.object(module, 'run_publication_child', return_value=(0, b'')) as process:
            self.walk.publication()
        self.assertFalse(list(self.run.glob('publication-child-*.json')))
        args, kwargs = process.call_args
        command = args[0]
        self.assertEqual(command[1:], ['-m', 'bt_runtime.fixtures', 'L03.listings', 'demo'])
        self.assertNotIn('docker', command)
        self.assertNotIn('private-token', ' '.join(command))
        self.assertEqual(kwargs['cwd'], self.run)
        env = kwargs['env']
        self.assertEqual(env['BT_DEMO_PRIVATE_TOKEN'], 'seller-private-token')
        self.assertEqual(env['BT_DEMO_IMPORT_ACK'], 'illustrative-stock-only')
        self.assertEqual(env['BT_DEMO_PRIVATE_DIAGNOSTICS'], '1')
        self.assertEqual(env['BT_MODULES_PATH'], str(module.ROOT / 'services/catalog/modules'))
        self.assertIn(str(self.run / 'domain-contracts'), env['PYTHONPATH'])
        self.assertEqual(env['BT_DEMO_ROOT'], str(self.run / 'demo'))
        self.assertEqual(env['TMPDIR'], str(self.run))
        self.assertEqual((self.run / 'demo/listings.json').read_bytes(),
                         (module.ROOT / 'demo/listings.json').read_bytes())
        self.assertEqual(stat.S_IMODE(self.walk.path.stat().st_mode), 0o600)
        self.assertNotIn('private-token', json.dumps(self.walk.evidence))

    def test_incomplete_publication_is_rejected(self):
        with patch.object(self.walk, 'login'), patch.object(self.walk, 'call', return_value={'items': []}), \
                patch.object(module, 'run_publication_child', return_value=(0, b'')):
            with self.assertRaises(AssertionError):
                self.walk.publication()

    def test_publication_failure_and_timeout_write_only_allowlisted_fields(self):
        arbitrary = (b'{\n  "refresh_token":\n    "unknown-refresh-secret"\n}\n'
                     b'Unstructured traceback with absent-from-env-token\n')
        tag = module.PUBLICATION_FAILURE_PREFIX
        good = tag + b'{"category":"publication_review_pending","http_status":503,"upstream":"identity"}\n'
        extra_key = tag + b'{"category":"upstream","http_status":429,"upstream":null,"other":"extra-secret"}\n'
        bad_type = tag + b'{"category":"upstream","http_status":true,"upstream":"identity"}\n'
        bad_value = tag + b'{"category":"unexpected-category","http_status":503,"upstream":"other-secret"}\n'
        bad_json = tag + b'{not a record with malformed-secret}\n'
        failures = [(1, arbitrary + good + extra_key + bad_type + bad_value + bad_json),
                    (None, arbitrary + extra_key + bad_type + bad_value + bad_json)]
        with patch.object(self.walk, 'login'), patch.object(self.walk, 'call') as http, \
                patch('builtins.print') as printed, patch.object(module, 'run_publication_child', side_effect=failures):
            for reason in ('failed', 'timed out'):
                with self.assertRaisesRegex(RuntimeError, f'^Local command {reason};') as caught:
                    self.walk.publication()
                self.assertIsNone(caught.exception.__cause__)
        http.assert_not_called()
        printed.assert_not_called()
        self.assertEqual(self.walk.evidence, [{'transport': 'native', 'status': 1},
                                              {'transport': 'native', 'status': 'timeout'}])
        records = {}
        for path in self.run.glob('publication-child-*.json'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            data = json.loads(path.read_text())
            records[data['timed_out']] = data
        self.assertEqual(records, {
            False: {'exit_code': 1, 'timed_out': False, 'exception_type': 'PublicationUnavailable',
                    'failure_category': 'publication_review_pending', 'http_status': 503, 'upstream': 'identity'},
            True: {'exit_code': None, 'timed_out': True, 'exception_type': 'TimeoutExpired',
                   'failure_category': 'timeout', 'http_status': None, 'upstream': None},
        })

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

    def test_competition_rejects_wrong_leader_and_public_ceiling_raise(self):
        # Mocked answers; test_bid_phase_follows_the_registered_proxy_rule checks the real rule.
        self.walk.state['auctions'] = {'DEMO-WATCH-01': {'auction_id': 'lot'}}
        prices = [10000, 11000, 12000, 16000, 20000, 20000, 20000]
        leaders = ['buyer-a', 'buyer-b', 'buyer-a', 'buyer-a', 'buyer-b', 'buyer-b', 'buyer-b']
        for wrong_leader, extra_bid in ((False, False), (True, False), (False, True)):
            index = -1
            def call(service, method, route, actor=None, body=None):
                nonlocal index
                if route.endswith('/history'):
                    return {'items': [{'amount_minor': 20000}] if extra_bid and index == 6 else [],
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

    def test_bid_phase_follows_the_registered_proxy_rule(self):
        # Prices and leaders come from the auction.proxy.v2 hook the auction service installs,
        # so the walkthrough's expectations cannot drift from the rule the service runs.
        folder = module.ROOT / 'services/auction/runtime/service_app'
        self.assertIn("setdefault('auction.proxy.v2', calculate)", (folder / 'main.py').read_text())
        spec = importlib.util.spec_from_file_location('registered_auction_app', folder / '__init__.py',
                                                      submodule_search_locations=[str(folder)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = package
        self.addCleanup(lambda: [sys.modules.pop(name, None) for name in list(sys.modules)
                                 if name.split('.')[0] == spec.name])
        spec.loader.exec_module(package)
        calculate = importlib.import_module(spec.name + '.proxy_v2').calculate
        # The hook takes account ids, which are UUIDs.
        ids = {'buyer-a': '00000000-0000-4000-8000-00000000000a', 'buyer-b': '00000000-0000-4000-8000-00000000000b'}
        opening, bands = 10000, [{'from_minor': 0, 'step_minor': 1000}]
        lot = {'current_minor': 0, 'leader_id': None, 'accepted_sequence': 0, 'revision': 1}
        maxima, public, bidders, posts = {}, [], set(), []
        self.walk.state['auctions'] = {'DEMO-WATCH-01': {'auction_id': 'lot'}}

        def call(service, method, route, actor=None, body=None):
            self.assertEqual(service, 'auction')
            if method == 'POST':
                kind = {'/v1/auctions/lot/bids': 'manual', '/v1/auctions/lot/maximum': 'maximum'}[route]
                self.assertEqual(body['expected_revision'], lot['revision'])
                # The same state the engine hands the hook (services/auction/runtime/service_app/engine.py).
                state = {'current_minor': max(lot['current_minor'], opening), 'opening_minor': opening,
                         'leader_id': lot['leader_id'], 'sequence': lot['accepted_sequence'],
                         'increment_bands': bands, 'maxima': [dict(entry) for entry in maxima.values()]}
                incoming = {'kind': kind, 'bidder_id': ids[actor], 'amount_minor': body['amount_minor'],
                            'sequence': lot['accepted_sequence'] + 1}
                posts.append(incoming)
                try:
                    result = calculate(json.loads(json.dumps(state)), dict(incoming))
                except ValueError as error:
                    return {'status': 'rejected', 'code': str(error)}
                sequence = lot['accepted_sequence']
                for bid in result['bids']:
                    sequence += 1
                    public.append({'sequence': sequence, 'amount_minor': bid['amount_minor'],
                                   'automatic': bid['automatic']})
                if sequence == lot['accepted_sequence']:
                    sequence += 1
                for entry in maxima.values():
                    entry['active'] = False
                maxima.update((entry['bidder_id'], dict(entry)) for entry in result['maxima'])
                lot.update(current_minor=result['current_minor'], leader_id=result['leader_id'],
                           accepted_sequence=sequence, revision=lot['revision'] + 1)
                bidders.add(actor)
                return {'status': 'succeeded'}
            if route == '/v1/auctions/lot/history':
                return {'items': [dict(item) for item in public], 'has_more': False}
            if route == '/v1/my-bids':
                # The status rule of services/auction/modules/bid-admission/routes.py.
                status = 'leading' if lot['leader_id'] == ids[actor] else 'outbid'
                return {'items': [{'auction_id': 'lot', 'my_status': status}] if actor in bidders else []}
            self.assertEqual((method, route), ('GET', '/v1/auctions/lot'))
            return {'revision': lot['revision'], 'current_minor': lot['current_minor']}

        with patch.object(self.walk, 'login'), patch.object(self.walk, 'wait_for_live'), \
                patch.object(self.walk, 'quote', return_value={'id': 'quote'}), \
                patch.object(self.walk, 'call', side_effect=call):
            self.walk.bids()
        proof = self.walk.state['bid_proof']
        self.assertEqual(len(proof['results']), len(posts))
        self.assertEqual(proof['results'][-1]['current_minor'], lot['current_minor'])
        self.assertEqual(proof['history']['items'], public)

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
        self.assertEqual(self.client.request.call_count, 2)

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

    def test_listing_review_uses_owning_requests_and_resumes_exact_publication_binding(self):
        ref = 'DEMO-WATCH-01'
        listing_id = '00000000-0000-4000-8000-000000000011'
        path = '/v1/listing-reviews/' + listing_id
        row = dict(id=listing_id, is_demo=True, status='draft', revision=8, seller_type='private',
                   physical_watch_id='00000000-0000-4000-8000-000000000012', facts={'reference': ref})
        current = {'state': 'required', 'revision': 0, 'assignment_revision': 0}
        sessions = {name: {'account': {'id': name + '-subject'}, 'access_token': name + '-private-token',
                          'principal': {'permissions': permissions}} for name, permissions in {
            'seller': [], 'operator': ['identity.private-seller.assign'],
            'reviewer': ['identity.private-seller.review'],
        }.items()}
        code_file, photo_file, inspected_file, verdict_file = [self.run / name for name in (
            'code.json', 'possession.png', 'reviewer-copy.png', 'verdict.json')]
        photo = module.PNG_SIGNATURE + b'unit-response-not-proof'
        photo_file.touch(mode=0o600)
        photo_file.write_bytes(photo)
        verdict_file.touch(mode=0o600)
        verdict_file.write_text(json.dumps({'verdict': 'approved', 'reason': 'Reviewed the supplied evidence'}))
        calls = []
        challenge_key = None

        def request(service, method, route, actor=None, body=None, **kwargs):
            nonlocal challenge_key
            if service == 'catalog':
                self.assertEqual((method, route, actor), ('GET', '/v1/seller/listings?limit=50', 'seller'))
                return {'items': [row]}
            self.assertEqual(service, 'identity')
            if route == path:
                self.assertEqual((method, actor), ('GET', 'seller'))
                return dict(current)
            action = route.removeprefix(path + '/')
            headers = kwargs['headers']
            role = {'challenges': 'seller', 'submissions': 'seller', 'assignment': 'operator',
                    'photo': 'reviewer', 'decision': 'reviewer'}[action]
            self.assertEqual(headers['Authorization'], 'Bearer ' + sessions[role]['access_token'])
            calls.append(action)
            if action == 'challenges':
                self.assertEqual(body, {'revision': 0})
                if challenge_key is None:
                    challenge_key = headers['Idempotency-Key']
                    current.update(state='issued', revision=1)
                    raise TimeoutError('Lost acknowledgement after issuing')
                self.assertEqual(headers['Idempotency-Key'], challenge_key)
                return {**current, 'challenge_id': 'owning-challenge', 'code': '654321'}
            if action == 'submissions':
                self.assertEqual(body, {'revision': 1, 'code': '654321', 'challenge_id': 'owning-challenge',
                                        'photo_base64': module.base64.b64encode(photo).decode()})
                current.update(state='pending', revision=2)
            elif action == 'assignment':
                self.assertEqual(body, {'revision': 2, 'reviewer_id': 'reviewer-subject'})
                current.update(revision=3, assignment_revision=1)
            elif action == 'photo':
                self.assertTrue(kwargs['raw'])
                return Mock(content=photo, headers={'content-type': 'image/png'})
            elif action == 'decision':
                self.assertEqual(body, {'revision': 3, 'assignment_revision': 1,
                                        'verdict': 'approved', 'reason': 'Reviewed the supplied evidence'})
                current.update(state='approved', revision=4)
            return dict(current)

        with patch.object(self.walk, 'private_demo_references', return_value={ref}), \
                patch.object(self.walk, 'login', side_effect=sessions.__getitem__), \
                patch.object(self.walk, 'listing_reviewer', return_value=sessions['reviewer']), \
                patch.object(self.walk, 'call', side_effect=request), patch('builtins.print') as printed:
            with self.assertRaises(TimeoutError):
                self.walk.listing_review(ref, 'challenge', code_file)
            self.walk.listing_review(ref, 'challenge', code_file)
            self.assertEqual(json.loads(code_file.read_text())['code'], '654321')
            self.assertEqual(stat.S_IMODE(code_file.stat().st_mode), 0o600)
            row['revision'] += 1
            with self.assertRaisesRegex(RuntimeError, 'exact draft'):
                self.walk.listing_review(ref, 'submit', photo_file)
            row['revision'] -= 1
            self.walk.listing_review(ref, 'submit', photo_file)
            self.walk.listing_review(ref, 'assign', None)
            with self.assertRaisesRegex(RuntimeError, 'must read'):
                self.walk.listing_review(ref, 'decide', verdict_file)
            self.walk.listing_review(ref, 'inspect', inspected_file)
            self.assertEqual(inspected_file.read_bytes(), photo)
            self.assertEqual(stat.S_IMODE(inspected_file.stat().st_mode), 0o600)
            self.walk.listing_review(ref, 'decide', verdict_file)
            published = {**row, 'status': 'published', 'revision': 9}
            self.walk.verify_reviewed_publication([published])
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                self.walk.verify_reviewed_publication([{**published, 'id': 'different-listing'}])
        self.assertEqual(calls, ['challenges', 'challenges', 'submissions', 'assignment', 'photo', 'decision'])
        persisted = self.walk.path.read_text()
        for private in ('654321', module.base64.b64encode(photo).decode(), 'Reviewed the supplied evidence'):
            self.assertNotIn(private, persisted)
            self.assertNotIn(private, str(printed.call_args_list))

    def test_listing_review_refuses_a_preapproved_record(self):
        row = dict(id='00000000-0000-4000-8000-000000000011', is_demo=True, status='draft', revision=8,
                   seller_type='private', physical_watch_id='watch', facts={'reference': 'DEMO-WATCH-01'})
        with patch.object(self.walk, 'private_demo_references', return_value={'DEMO-WATCH-01'}), \
                patch.object(self.walk, 'login', return_value={'account': {'id': 'seller'}}), \
                patch.object(self.walk, 'call', side_effect=[{'items': [row]}, {'state': 'approved', 'revision': 4}]) as call:
            with self.assertRaisesRegex(RuntimeError, 'existing approvals cannot count'):
                self.walk.listing_review('DEMO-WATCH-01', 'challenge', self.run / 'challenge.json')
        self.assertEqual(call.call_count, 2)
        self.assertNotIn('DEMO-WATCH-01', self.walk.state['listing_proofs'])

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
        prices = [10000, 11000, 12000, 16000, 20000, 20000, 20000]
        leaders = ['buyer-a', 'buyer-b', 'buyer-a', 'buyer-a', 'buyer-b', 'buyer-b', 'buyer-b']
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
        self.assertEqual(len(committed), 7)
        self.assertEqual(committed[uncertain[0]], uncertain[1])
        self.assertIn('bids', resumed.state['completed_phases'])
        self.assertEqual(index, 6)

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
