import fcntl
import hashlib
import hmac
import json
from pathlib import Path
import tempfile

import pytest
import unittest
from unittest.mock import patch, Mock

from native import ROOT, STORE_PATH, CandidateRuntime, Execution, Unavailable


def test_spawn_restores_signal_mask_with_an_active_output_reader(tmp_path):
    import signal
    import subprocess
    import sys
    import time

    from native import running

    execution = ExecutionTests().execution(tmp_path)
    code = """
import signal
import sys

mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])
sys.exit(int(signal.SIGTERM in mask or signal.SIGALRM in mask or signal.SIGUSR1 not in mask))
"""
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    try:
        first = execution.spawn('first', [sys.executable, '-c', 'import time; time.sleep(20)'],
                                tmp_path, {})
        assert first['reader'].is_alive()
        with patch('native.subprocess.Popen', wraps=subprocess.Popen) as start:
            second = execution.spawn('second', [sys.executable, '-c', code], tmp_path, {})['child']
        assert start.call_args.kwargs.get('preexec_fn') is None
        deadline = time.monotonic() + 5
        while running(second) and time.monotonic() < deadline:
            time.sleep(.01)
        assert not running(second)
        execution.stop('second')
        assert second.returncode == 0
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        execution.close()


class ExecutionTests(unittest.TestCase):
    def execution(self, root):
        settings = root / 'native-v1.json'
        settings.write_text(json.dumps({'schema_version': 1,
            'python': '/tmp/test-python/bin/python',
            'postgres_bin': '/tmp/test-postgres/bin',
            'services': {
                'orders': {'env': {
                    'BT_DATABASE_URL': 'postgresql://bt_orders:test-runtime@127.0.0.1:54329/bt_orders',
                    'BT_DATABASE_OWNER_URL': 'postgresql://bt_orders_owner:test-owner@127.0.0.1:54329/bt_orders',
                    'BT_MIGRATION_DATABASE_URL': 'postgresql://bt_orders_owner:test-owner@127.0.0.1:54329/bt_orders',
                    'CATALOG_API_URL': 'http://127.0.0.1:8102',
                    'BT_SIMULATED_PAYMENT_SECRET': 'test-' + 'payment-secret-' * 3,
                    'BT_SIGNING_KEY': 'test-scoped-signing-key'}},
                'web': {'env': {'HOSTNAME': '127.0.0.1', 'PORT': '3000'}}}}))
        execution = Execution(root, settings)
        execution.candidate_runtime = CandidateRuntime(root / 'test-store', '/tmp/test-site',
                                       'test-runtime-fingerprint', '/tmp/test-python/bin/python')
        return execution

    def test_external_provider_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.settings['services']['orders']['env']['PAYMENT_URL'] = 'https://example.invalid'
            with self.assertRaisesRegex(Unavailable, 'loopback-runtime-settings'):
                execution.environment('orders', Path(folder))

    def test_generated_settings_retained_and_paths_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            release = Path(folder) / 'test-release'
            env = execution.environment('orders', release)
            self.assertIn('@127.0.0.1:54329/', env['BT_DATABASE_URL'])
            self.assertEqual(env['BT_SERVICE_NAME'], 'orders')
            self.assertEqual(env['BT_SIGNING_KEY'], 'test-scoped-signing-key')
            self.assertNotIn('BT_DATABASE_OWNER_URL', env)
            self.assertNotIn('BT_MIGRATION_DATABASE_URL', env)
            self.assertEqual(env['CATALOG_API_URL'], 'http://127.0.0.1:8102')
            self.assertEqual(env['BT_MODULES_PATH'], str(release / 'services/orders/modules'))
            self.assertIn(str(release / 'contracts'), env['PYTHONPATH'])

    def test_invalid_settings_refused_before_control_or_termination(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.settings['services']['orders']['env']['PAYMENT_URL'] = 'https://example.invalid'
            with patch('native.os.killpg') as kill:
                with self.assertRaisesRegex(Unavailable, 'loopback-runtime-settings'):
                    execution.replace('orders', Path(folder), 'test-release')
                kill.assert_not_called()
            self.assertFalse((Path(folder) / 'control.lock').exists())

    def test_control_lock_excludes_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            execution = self.execution(root)
            with (root / 'control.lock').open('a') as control:
                fcntl.flock(control, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch('native.os.killpg') as kill:
                    with self.assertRaisesRegex(Unavailable, 'native-supervisor-control-busy'):
                        execution.replace('orders', root, 'test-release')
                    kill.assert_not_called()

    def test_missing_restore_never_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            with self.assertRaisesRegex(Unavailable, 'E04-connected-backup-output'):
                execution.call('restore', {})

    def test_restart_uses_built_release(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.releases['test-revision'] = Path(folder)
            with patch.object(execution, 'replace', return_value={}) as replace:
                answer = execution.call('restart', {'candidate': 'test-revision',
                                                    'service': 'orders'})
            replace.assert_called_once_with('orders', Path(folder), 'test-revision:orders')
            self.assertEqual(answer['source'], 'native')

    def test_foreign_process_never_signalled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            execution = self.execution(root)
            (root / 'ledger.json').write_text(json.dumps({'processes': [
                {'name': 'orders', 'pid': 42, 'start_ticks': 'test-old'}]}))
            with patch('native.ticks', return_value='test-new'), patch('native.os.killpg') as kill:
                with self.assertRaisesRegex(Unavailable, 'native-supervisor-ownership-transfer'):
                    execution.replace('orders', root, 'test-artifact')
                kill.assert_not_called()

    def test_reads_require_owned_database_and_use_launched_runtime_url(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            with self.assertRaisesRegex(Unavailable, 'owned-orders-observations'):
                execution.reads()
            execution.children = {
                'database': {'child': Mock()},
                'orders': {'child': Mock(), 'env': execution.environment('orders', Path(folder))},
                'communications': {'child': Mock(), 'env': {'BT_DATABASE_URL': 'test-comms-url'}},
            }
            with patch('native.running', return_value=True), \
                    patch('observations.read_orders') as read:
                self.assertIs(execution.reads(), read.return_value)
            read.assert_called_once_with(
                ['-d', execution.children['orders']['env']['BT_DATABASE_URL']], ['-d', 'test-comms-url'])

    def test_web_only_receives_consumed_public_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            scoped = execution.settings['services']['web']['env']
            scoped.update(BT_SIGNING_KEY='test-key', BT_AUTH_PRIVATE_PEM='test-private',
                          NODE_OPTIONS='test-private-option', CATALOG_URL='test-unused',
                          BT_PUBLIC_WEB_ORIGINS='http://localhost:3000,http://127.0.0.1:3000',
                          CATALOG_API_URL='http://127.0.0.1:8102')
            env = execution.environment('web', Path(folder))
            self.assertEqual(set(env) & set(scoped),
                             {'HOSTNAME', 'PORT', 'BT_PUBLIC_WEB_ORIGINS', 'CATALOG_API_URL'})
            self.assertEqual(env['CATALOG_API_URL'], scoped['CATALOG_API_URL'])
            scoped['CATALOG_API_URL'] = 'http://127.0.0.1:8102/?test-private'
            with self.assertRaisesRegex(Unavailable, 'web-private-settings'):
                execution.environment('web', Path(folder))

    def test_database_url_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            supplied = execution.settings['services']['orders']['env']['BT_DATABASE_URL']
            self.assertEqual(execution.environment('orders', Path(folder))['BT_DATABASE_URL'], supplied)
            execution.settings['services']['orders']['env']['BT_DATABASE_URL'] = supplied.replace('54329', '5432')
            with self.assertRaisesRegex(Unavailable, 'runtime-database'):
                execution.environment('orders', Path(folder))

    def test_replacement_records_owned_handles_and_prior_release(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            before = dict(child=Mock(pid=123), start='test-before', root=Path(folder),
                          artifact='test-prior', env={})
            before['child'].poll.return_value = None
            after = dict(child=Mock(pid=124), start='test-after')
            execution.children['orders'] = before
            root = Path(folder)
            execution.releases['test-current'] = root
            execution.images[root] = Mock(closed=False)
            execution.orders_executables[root] = 'test-orders-executable'
            with patch('native.running', return_value=True), patch.object(execution, 'isolated'), \
                    patch.object(execution, 'stop') as stop, patch.object(execution, 'launch', return_value=after):
                result = execution.replace('orders', root, 'test-current:orders')
            stop.assert_called_once_with('orders')
            self.assertEqual(result['before_artifact'], 'test-prior')
            self.assertEqual(result['after_pid'], 124)
            self.assertIs(execution.previous['orders'], before)

    def test_failed_replacement_relaunches_prior_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            before = dict(child=Mock(pid=123), start='test-before', root=Path(folder),
                          artifact='test-prior', argv=('test-prior-command',),
                          env={'TEST_SETTING': 'test-value'})
            before['child'].poll.return_value = None
            execution.children['orders'] = before
            root = Path(folder)
            execution.releases['test-current'] = root
            execution.images[root] = Mock(closed=False)
            execution.orders_executables[root] = 'test-orders-executable'
            with patch('native.running', return_value=True), patch.object(execution, 'isolated'), \
                    patch.object(execution, 'stop'), patch.object(execution, 'launch', side_effect=[Unavailable('test-readiness'), {}]) as launch:
                with self.assertRaisesRegex(Unavailable, 'test-readiness'):
                    execution.replace('orders', root, 'test-current:orders')
            self.assertEqual(launch.call_args.args, ('orders', Path(folder), 'test-prior', before['env']))
            self.assertEqual(launch.call_args.kwargs['invocation']['argv'], before['argv'])

    def test_missing_prior_and_command_are_named(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            with patch.object(execution, 'isolated'):
                with self.assertRaisesRegex(Unavailable, 'compatible-prior-release-input'):
                    execution.start()
            with self.assertRaisesRegex(Unavailable, 'product-command-reference'):
                execution.recover_command('test-artifact')

    def bind_recovery_attempt(self, execution):
        facts = dict(order_id='test-order', buyer_id='test-buyer', quote_id='test-quote',
                     quote_revision=1, currency='USD', total_minor=100, route='card',
                     reference='test-provider-reference')
        execution.callback_acknowledged = Mock(return_value=True)
        execution.payment_attempts['test-attempt'] = dict(facts, sequence=0)
        execution.settings['e09_command'] = {'body': dict(
            facts, event_id='test-event', outcome='confirmed',
            attempt_id='test-attempt', sequence=1),
            'headers': {'x-bt-signature': 'test-untrusted', 'content-length': '0'}}
        return {'receipts': [{'operation_id': 'test-baseline',
                              'attempt': {'order_id': 'test-baseline-order'}}]}

    def test_recovery_discards_response_and_retries_identical_product_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            baseline = self.bind_recovery_attempt(execution)
            execution.children['orders'] = dict(root=Path(folder), artifact='test-artifact')
            with patch('native.http.client.HTTPConnection') as connect:
                with self.assertRaisesRegex(Unavailable, 'recovered-candidate-orders-artifact'):
                    execution.recover_command('test-other-artifact')
                connect.assert_not_called()
            receipt = dict(operation_id='test-event', amount_minor=100, currency='USD',
                           custody_reference='test-custody', revision=1, paid=True,
                           order_state='paid_held', attempt_state='confirmed',
                           attempt={'id': 'test-attempt', 'order_id': 'test-order'})
            rows = dict(receipts=[receipt], journal=[dict(receipt, effect_count=1)],
                        custody=[receipt], inbox=[receipt], outbox=[receipt])
            connection = Mock()
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = (
                b'{"status":"succeeded","paid":true,"attempt":'
                b'{"state":"confirmed","id":"test-attempt","order_id":"test-order"}}')
            with patch('native.http.client.HTTPConnection', return_value=connection), \
                    patch.object(execution, 'reads',
                                 side_effect=[baseline, dict(rows, inbox=[]), rows, rows]), \
                    patch('native.time.sleep'), \
                    patch.object(execution, 'replace', return_value={
                        'before_artifact': 'test-artifact', 'artifact': 'test-artifact'}):
                result = execution.recover_command('test-artifact')
            self.assertEqual(result['product_operation_ids'], ['test-event'])
            self.assertEqual(connection.request.call_args_list[0], connection.request.call_args_list[1])
            sent = connection.request.call_args_list[0]
            self.assertEqual(sent.args[1], '/callbacks/v1/simulated')
            key = execution.settings['services']['orders']['env']['BT_SIMULATED_PAYMENT_SECRET']
            self.assertEqual(sent.args[3]['X-BT-Signature'],
                             hmac.new(key.encode(), sent.args[2], hashlib.sha256).hexdigest())
            self.assertNotIn('x-bt-signature', sent.args[3])
            self.assertNotIn('content-length', sent.args[3])
            self.assertEqual(connection.getresponse.call_count, 1)
            self.assertEqual(connection.close.call_count, 2)
            response = connection.getresponse.return_value
            response.read.return_value = response.read.return_value.replace(b'true', b'false')
            with patch('native.http.client.HTTPConnection', return_value=connection), \
                    patch.object(execution, 'reads', side_effect=[baseline, rows]), \
                    patch.object(execution, 'replace', return_value={
                        'before_artifact': 'test-artifact', 'artifact': 'test-artifact'}):
                with self.assertRaisesRegex(Unavailable, 'retried-current-held-payment'):
                    execution.recover_command('test-artifact')

    def test_recovery_requires_retained_outbox_and_inbox(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            baseline = self.bind_recovery_attempt(execution)
            execution.children['orders'] = dict(root=Path(folder), artifact='test-artifact')
            receipt = dict(operation_id='test-event', amount_minor=100, currency='USD',
                           custody_reference='test-custody', revision=1, paid=True,
                           order_state='paid_held', attempt_state='confirmed',
                           retained_quote={'snapshot': {'buyer_fee_minor': 10,
                                                        'shipping_minor': 5, 'payable_minor': 100}},
                           attempt={'id': 'test-attempt', 'order_id': 'test-order'})
            rows = dict(receipts=[receipt], journal=[dict(receipt, effect_count=1)],
                        custody=[receipt], inbox=[receipt], outbox=[receipt])
            changed = dict(rows, outbox=[dict(receipt, revision=2)])
            repriced = dict(rows, receipts=[dict(receipt, retained_quote={'snapshot': {
                'buyer_fee_minor': 9, 'shipping_minor': 6, 'payable_minor': 100}})])
            connection = Mock()
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = (
                b'{"status":"succeeded","paid":true,"attempt":'
                b'{"state":"confirmed","id":"test-attempt","order_id":"test-order"}}')
            for before, after, reason in (
                (rows, changed, 'retained-product-outbox'),
                (rows, repriced, 'retained-product-receipts'),
                (dict(rows, inbox=[]), rows, 'communications-payment-confirmed-delivery'),
                (rows, dict(rows, inbox=[]), 'communications-payment-confirmed-delivery'),
            ):
                connection.reset_mock()
                with patch('native.http.client.HTTPConnection', return_value=connection), \
                        patch.object(execution, 'reads', side_effect=[baseline, before, after]), \
                        patch.object(execution, 'await_payment_inbox', return_value=before), \
                        patch.object(execution, 'replace', return_value={
                            'before_artifact': 'test-artifact', 'artifact': 'test-artifact'}) as replace:
                    with self.assertRaisesRegex(Unavailable, reason):
                        execution.recover_command('test-artifact')
                replace.assert_called_once()
                self.assertEqual(connection.request.call_count, 2)
                self.assertEqual(execution.acknowledged_callback_id, 'test-event')

    def test_recovery_rejects_callback_outside_journey_before_sending(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            self.bind_recovery_attempt(execution)
            execution.children['orders'] = {'artifact': 'test-artifact'}
            execution.settings['e09_command']['body']['reference'] = 'test-unrelated'
            with patch('native.http.client.HTTPConnection') as connect:
                with self.assertRaisesRegex(Unavailable, 'journey-payment-attempt'):
                    execution.recover_command('test-artifact')
                connect.assert_not_called()

    def test_reused_process_identity_is_never_signalled(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            child = Mock(pid=123)
            child.poll.return_value = None
            execution.children['orders'] = dict(child=child, start='test-before', session=123)
            with patch('native.ticks', return_value='test-after'), patch('native.os.killpg') as kill:
                with self.assertRaisesRegex(Unavailable, 'owned-process-identity'):
                    execution.stop('orders')
                kill.assert_not_called()

    def test_product_preparation_resolves_real_response_values(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.settings['e09_journey'] = [
                dict(id='order', service='orders', path=['/v1/orders'], body={},
                     expect={'status': 'succeeded'}),
                dict(id='attempt', service='orders',
                     path=['/v1/orders/', {'$result': 'order/id'}, '/payment-attempts'],
                     body={'expected_revision': {'$result': 'order/revision'}},
                     expect={'status': 'succeeded'})]
            connection = Mock()
            response = connection.getresponse.return_value
            response.status = 200
            response.read.side_effect = [
                b'{"status":"succeeded","id":"test-order","revision":2}',
                b'{"status":"succeeded","attempt":{"id":"test-attempt"}}']
            with patch('native.http.client.HTTPConnection', return_value=connection):
                execution.prepare_products()
            call = connection.request.call_args_list[1]
            self.assertEqual(call.args[1], '/v1/orders/test-order/payment-attempts')
            self.assertEqual(json.loads(call.args[2]), {'expected_revision': 2})
            self.assertEqual(execution.resolve_product({'$result': 'attempt/attempt/id'}),
                             'test-attempt')

    def test_product_preparation_denial_stops_journey(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.settings['e09_journey'] = [dict(id='order', service='orders',
                path=['/v1/orders'], body={}, expect={'status': 'succeeded'})]
            connection = Mock()
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = b'{"status":"denied"}'
            with patch('native.http.client.HTTPConnection', return_value=connection):
                with self.assertRaisesRegex(Unavailable, 'product-preparation-outcome'):
                    execution.prepare_products()
            self.assertEqual(execution.product_results, {})

    def test_dead_leader_still_terminates_owned_group(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            child = Mock(pid=123)
            execution.children['orders'] = dict(child=child, start='test-start',
                                                session=123, reader=Mock())
            member = Mock()
            member.parent.name = '124'
            member.read_text.return_value = '124 (test-child) S 1 123 123 0'
            with patch('native.Path.glob', side_effect=[[member], []]), \
                    patch('native.ticks', return_value='test-start'), \
                    patch('native.os.getsid', return_value=123), \
                    patch('native.os.killpg') as kill:
                execution.stop('orders')
            kill.assert_called_once_with(123, __import__('signal').SIGTERM)
            child.poll.assert_not_called()
            self.assertNotIn('orders', execution.children)

    def test_group_escalation_keeps_leader_unreaped_until_signals_complete(self):
        import signal
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            child = Mock(pid=123)
            execution.children['orders'] = dict(child=child, start='test-start',
                                                session=123, reader=Mock())
            member = Mock()
            member.read_text.return_value = '123 (test-leader) S 1 123 123 0'
            def send(pid, number):
                self.assertEqual(pid, 123)
                child.wait.assert_not_called()
                child.poll.assert_not_called()
            with patch('native.Path.glob', side_effect=[[member], [member], [member], []]), \
                    patch('native.ticks', return_value='test-start'), \
                    patch('native.os.getsid', return_value=123), \
                    patch('native.time.monotonic', side_effect=[0, 11, 12]), \
                    patch('native.os.killpg', side_effect=send) as kill:
                execution.stop('orders')
            self.assertEqual([call.args[1] for call in kill.call_args_list],
                             [signal.SIGTERM, signal.SIGKILL])
            child.wait.assert_called_once_with(timeout=5)

    def test_prior_inventory_and_revision_are_bound_to_reviewed_bytes(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repository = root / 'repository'
            repository.mkdir()
            def git(*args):
                return subprocess.run(['git', *args], cwd=repository, check=True,
                                      capture_output=True).stdout.decode().strip()
            git('init', '-q')
            source = repository / 'services/orders/app.py'
            source.parent.mkdir(parents=True)
            source.write_text('VERSION = "test-prior"\n')
            schema = repository / 'schema.sql'
            schema.write_text('-- test-schema\n')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                'commit', '-qm', 'test prior')
            revision = git('rev-parse', 'HEAD')
            release = root / 'release'
            (release / 'services/orders').mkdir(parents=True)
            (release / 'services/orders/app.py').write_bytes(source.read_bytes())
            (release / 'schema.sql').write_bytes(schema.read_bytes())
            source.write_text('VERSION = "test-current"\n')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                'commit', '-qm', 'test current')
            execution = self.execution(root)
            approval = root / 'approval.json'
            def prior_input():
                files = {p.relative_to(release).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in release.rglob('*') if p.is_file()}
                digest = hashlib.sha256()
                for name, value in sorted(files.items()):
                    digest.update(name.encode() + b'\0' + value.encode() + b'\n')
                prior = dict(source_revision=revision, files=files, artifact=digest.hexdigest(),
                             config_hash='test-config', schema_hash=files['schema.sql'],
                             schema_file='schema.sql')
                approval.write_text(json.dumps(dict(prior, schema_version=1,
                                                     compatible=True, reviewed_by='test-reviewer')))
                return dict(prior, provenance_file=str(approval),
                            provenance_hash=hashlib.sha256(approval.read_bytes()).hexdigest())
            with patch('native.ROOT', repository), \
                    patch('native.os.statvfs', return_value=Mock(f_flag=__import__('os').ST_RDONLY)):
                prior = prior_input()
                execution.verify_prior(release, prior)
                partial = dict(prior, files={'schema.sql': prior['schema_hash']})
                with self.assertRaisesRegex(Unavailable, 'complete-prior-artifact'):
                    execution.verify_prior(release, partial)
                (release / 'services/orders/app.py').write_bytes(source.read_bytes())
                with self.assertRaisesRegex(Unavailable, 'prior-source-content'):
                    execution.verify_prior(release, prior_input())
                approval.write_text('{}')
                with self.assertRaisesRegex(Unavailable, 'prior-provenance-hash'):
                    execution.verify_prior(release, prior_input() | {'provenance_hash': 'test-invalid'})

    def test_partial_creation_is_reaped_on_identity_or_reader_failure(self):
        for failure in ('identity', 'reader'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                execution = self.execution(Path(folder))
                child = Mock(pid=123)
                with patch('native.subprocess.Popen', return_value=child), \
                        patch('native.ticks', side_effect=ValueError('test-identity')
                              if failure == 'identity' else None, return_value='test-start'), \
                        patch('native.os.getsid', return_value=123), \
                        patch('native.threading.Thread.start', side_effect=ValueError('test-reader')), \
                        patch('native.os.killpg') as kill:
                    with self.assertRaisesRegex(ValueError, 'test-' + failure):
                        execution.spawn('orders', ['test-command'], Path(folder), {})
                kill.assert_called_once_with(123, __import__('signal').SIGKILL)
                child.wait.assert_called_once_with(timeout=5)
                self.assertEqual(execution.children, {})


def test_authority_requires_real_allowed_and_denied_results():
    execution = Execution.__new__(Execution)
    execution.product_results = {}
    roles = ('allowed', 'denied')
    origin = 'http://localhost:3000'
    refresh = 'test-refresh-' * 3
    execution.services = {'identity': {'port': 8101}}
    execution.participants = {r: (r, 'test-expired-' + r, refresh, origin) for r in roles}
    execution.settings = {'e09_authority': {
        role: {'path': ['/v1/orders/test-order'], 'headers': {'Authorization': {'$bearer': role}},
               'expect': {'status': status}}
        for role, status in zip(roles, ('succeeded', 'denied'))}}
    connection = Mock()

    def refreshed(role):
        body = json.dumps({'account': {'id': role}, 'access_token': 'test-fresh-' + role})
        return Mock(status=200, read=Mock(return_value=body.encode()),
                    getheader=Mock(return_value='bt_refresh=' + 'test-successor-' * 3))

    allowed = Mock(status=200, read=Mock(return_value=b'{"status":"succeeded"}'))
    denied = Mock(status=403, read=Mock(return_value=b'{"status":"denied"}'))
    connection.getresponse.side_effect = [refreshed('allowed'), allowed, refreshed('denied'), denied]
    with patch('native.http.client.HTTPConnection', return_value=connection):
        assert execution.authority('test-order') is True
    for index, role in enumerate(roles):
        refresh_request, probe = connection.request.call_args_list[index * 2:index * 2 + 2]
        assert refresh_request.args == ('POST', '/v1/accounts/refresh')
        assert refresh_request.kwargs['headers'] == {'Origin': origin, 'Cookie': 'bt_refresh=' + refresh}
        assert probe.kwargs['headers']['Authorization'] == 'Bearer test-fresh-' + role

    import pytest
    connection.getresponse.side_effect = [refreshed('allowed'), allowed, refreshed('denied'), allowed]
    with patch('native.http.client.HTTPConnection', return_value=connection):
        with pytest.raises(Unavailable, match='current-authority-denied'):
            execution.authority('test-order')

    connection.getresponse.side_effect = [refreshed('denied')]
    connection.request.reset_mock()
    with patch('native.http.client.HTTPConnection', return_value=connection):
        with pytest.raises(Unavailable, match='authority-session-identity'):
            execution.authority('test-order')
    assert connection.request.call_count == 1

    probes = execution.settings['e09_authority']
    for probe in probes.values():
        probe['path'] = ['/v1/orders/test-other']
    with patch('native.http.client.HTTPConnection') as connect:
        with pytest.raises(Unavailable, match='authority-recovered-order'):
            execution.authority('test-order')
        connect.assert_not_called()

    for probe in probes.values():
        probe['path'] = ['/v1/orders/test-order']
    probes['denied']['headers']['Authorization'] = {'$bearer': 'allowed'}
    with pytest.raises(Unavailable, match='same-order-distinct-participants'):
        execution.authority('test-order')


def test_registration_authorizes_next_request(tmp_path):
    execution = ExecutionTests().execution(tmp_path)
    execution.settings['e09_journey'] = [
        dict(id='buyer', service='identity', path=['/v1/accounts/register'],
             body={}, headers={'Origin': 'http://localhost:3000'}, expect={'token_type': 'Bearer'}),
        dict(id='order', service='orders', path=['/v1/orders'], body={},
             headers={'Authorization': {'$bearer': 'buyer'}}, expect={'accepted': True})]
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 201
    response.getheader.return_value = 'bt_refresh=' + 'test-refresh-' * 3
    response.read.side_effect = [b'{"token_type":"Bearer","account":{"id":"test-buyer"},'
                                 b'"access_token":"test-token"}', b'{"accepted":true}']
    with patch('native.http.client.HTTPConnection', return_value=connection):
        execution.prepare_products()
    assert connection.request.call_args.args[3]['Authorization'] == 'Bearer test-token'


def test_config_pin_survives_rotation_but_binds_route(tmp_path):
    from native import config_digest
    execution = ExecutionTests().execution(tmp_path)
    env = execution.environment('orders', tmp_path)
    def digest():
        return config_digest({'orders': env}, tmp_path, tmp_path)
    original = digest()
    env.update(BT_SIGNING_KEY='test-rotated', BT_DATABASE_URL=env['BT_DATABASE_URL'].replace(
        'test-runtime', 'test-rotated'))
    assert digest() == original
    env['CATALOG_API_URL'] += '/changed'
    assert digest() != original


def test_candidate_web_build_runs_navigation_generation_before_compilation(tmp_path):
    import io
    import tarfile

    execution = ExecutionTests().execution(tmp_path)
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode='w') as archive:
        archive.add(ROOT / 'web/package.json', arcname='web/package.json')

    def command(argv, cwd, env):
        if 'infra/foundation/package-contracts.py' in argv:
            return
        target = tmp_path / 'scenarios/e09/releases/candidate'
        web = target / 'web'
        assert cwd == tmp_path
        assert argv == [*execution.application_namespace(), '--bind', str(target), str(target),
                        '--ro-bind', str(execution.candidate_runtime.store), str(target / STORE_PATH),
                        '--chdir', str(web), '--', 'npm', 'run', 'build']
        assert not (web / 'registry.generated.ts').exists()
        scripts = json.loads((web / 'package.json').read_text())['scripts']
        assert [step.strip() for step in scripts[argv[-1]].split('&&')] == [
            'node scripts/generate-nav.mjs', 'next build']

    with patch.object(execution, 'isolated'), \
            patch('native.candidate_runtime', return_value=execution.candidate_runtime), \
            patch('native.subprocess.run', return_value=Mock(stdout=archive_bytes.getvalue())), \
            patch('native.compileall.compile_dir', return_value=True), \
            patch('native.bind_web_dependencies') as bind, \
            patch('native.orders_executable_digest', return_value='test-orders'), \
            patch('native.seal_release', return_value=(Mock(), 'test-artifact')), \
            patch('native.retain_archive') as retain, \
            patch.object(execution, 'command', side_effect=command) as run:
        result = execution.build({'source_revision': 'test-source', 'operation_id': 'test-build'})
    assert result['archive_mode'] == 'built'
    assert run.call_count == 2
    bind.assert_called_once_with(ROOT, tmp_path / 'scenarios/e09/releases/candidate')
    assert retain.call_args.args[1] == tmp_path / 'scenarios/e09'


def test_release_dependencies_rebind_workspace_and_require_read_only_store(tmp_path):
    import os
    from native import bind_web_dependencies

    checkout = tmp_path / 'checkout'
    release = tmp_path / 'release'
    store = checkout / 'node_modules/.pnpm'
    next_package = store / 'next/node_modules/next'
    next_bin = next_package / 'dist/bin/next'
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text('test-entry')
    web = checkout / 'web/node_modules'
    scope = web / '@beirut-time'
    scope.mkdir(parents=True)
    for name in ('contracts-core', 'i18n', 'ui'):
        installed = checkout / 'packages' / name
        installed.mkdir(parents=True)
        (scope / name).symlink_to(installed)
        exported = release / 'packages' / name
        exported.mkdir(parents=True)
        (exported / 'package.json').write_text(json.dumps({'name': '@beirut-time/' + name}))
    (web / 'next').symlink_to(next_package)
    installed_ui = checkout / 'packages/ui/node_modules'
    installed_ui.mkdir()
    (installed_ui / 'next').symlink_to(next_package)

    with patch('native.os.statvfs', return_value=Mock(f_flag=0)):
        with pytest.raises(Unavailable, match='immutable-release-dependency'):
            bind_web_dependencies(checkout, tmp_path / 'rejected')

    with patch('native.os.statvfs', return_value=Mock(f_flag=os.ST_RDONLY)):
        bind_web_dependencies(checkout, release)
    for name in ('contracts-core', 'i18n', 'ui'):
        link = release / 'web/node_modules/@beirut-time' / name
        assert not Path(os.readlink(link)).is_absolute()
        assert link.resolve() == release / 'packages' / name
    mount = release / STORE_PATH
    assert mount.is_dir() and not list(mount.iterdir())
    assert (release / 'packages/ui/node_modules/next').resolve() == mount / next_package.relative_to(store)
    assert (release / 'web/node_modules/.bin/next').resolve() == mount / next_bin.relative_to(store)


def test_archive_handoff_preserves_exact_sealed_bytes_after_cleanup(tmp_path):
    import stat
    from native import retain_archive, seal_release

    execution = ExecutionTests().execution(tmp_path)
    source = tmp_path / 'release'
    source.mkdir()
    (source / 'application.py').write_text('test-release')
    output = tmp_path / 'output'
    output.mkdir(mode=0o700)
    image, digest = seal_release(source)
    execution.images[source] = image
    with patch('native.ARCHIVE_LIMIT', 1):
        with pytest.raises(Unavailable, match='bounded-release-archive'):
            retain_archive(image, output)
    assert not list(output.iterdir())
    retain_archive(image, output)
    with pytest.raises(Unavailable, match='fresh-release-archive-handoff'):
        retain_archive(image, output)
    execution.close()
    assert image.closed
    handoff, = output.iterdir()
    assert handoff.name == 'candidate.tar'
    assert stat.S_IMODE(handoff.stat().st_mode) == 0o400
    assert hashlib.sha256(handoff.read_bytes()).hexdigest() == digest


def test_sealed_image_preserves_executable_bytes(tmp_path):
    import pytest
    import tarfile
    from native import seal_release
    source = tmp_path / 'service.py'
    source.write_bytes(b'test-original')
    image, artifact = seal_release(tmp_path)
    with image:
        source.write_bytes(b'test-changed')
        image.seek(0)
        assert hashlib.file_digest(image, 'sha256').hexdigest() == artifact
        image.seek(0)
        with tarfile.open(fileobj=image) as archive:
            assert archive.extractfile('./service.py').read() == b'test-original'
        with pytest.raises(PermissionError):
            __import__('os').ftruncate(image.fileno(), 0)


def test_current_launch_reads_sealed_image_on_each_start(tmp_path):
    import tarfile
    from native import seal_release
    execution = ExecutionTests().execution(tmp_path)
    release = tmp_path / 'release'
    release.mkdir()
    source = release / 'service.py'
    source.write_bytes(b'test-approved')
    image, artifact = seal_release(release)
    source.write_bytes(b'test-modified')
    def spawn(service, argv, cwd, env, stdin):
        mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg == '--tmpfs']
        assert mounts == [str(tmp_path), str(release)]
        assert '--unshare-pid' in argv
        script = argv[argv.index('-c') + 1]
        assert '--ro-bind "$root" "$root"' in script
        assert '--ro-bind "$store" "$store_mount"' in script
        assert argv[argv.index('e09') + 3:argv.index('e09') + 5] == (
            str(execution.candidate_runtime.store), str(release / STORE_PATH))
        assert execution.candidate_runtime.python in argv
        with tarfile.open(fileobj=stdin) as snapshot:
            assert snapshot.extractfile('./service.py').read() == b'test-approved'
        return {'child': Mock(poll=Mock(return_value=None))}
    with image, patch('native.running', return_value=True), \
            patch.object(execution, 'isolated'), patch.object(execution, 'ready'), \
            patch.object(execution, 'spawn', side_effect=spawn):
        execution.images[release] = image
        for _ in range(2):
            assert execution.launch('orders', release, artifact, {'PYTHONPATH': 'test-release-imports'})['artifact'] == artifact


def test_prior_web_launch_masks_private_run_and_process_view(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    execution = ExecutionTests().execution(run)
    prior = tmp_path / 'prior'
    with patch.object(execution, 'isolated'), patch.object(execution, 'ready'), \
            patch('native.running', return_value=True), patch.object(execution, 'spawn') as spawn:
        execution.launch('web', prior, 'test-prior', {'PORT': '3000'})
    service, argv, cwd, env = spawn.call_args.args
    assert service == 'web' and cwd == run and env == {'PORT': '3000'}
    assert argv[argv.index('--tmpfs') + 1] == str(run)
    assert argv[argv.index('--proc') + 1] == '/proc'
    assert '--unshare-pid' in argv
    assert argv[argv.index('--chdir') + 1] == str(prior / 'web')


def test_catalog_upload_sends_photo_bytes_and_retains_listing_revision(tmp_path):
    from io import BytesIO
    from PIL import Image
    import pytest

    image = BytesIO()
    Image.new('RGB', (16, 16)).save(image, format='PNG')
    photo = tmp_path / 'watch.png'
    photo.write_bytes(image.getvalue())
    listing = '00000000-0000-4000-8000-000000000001'
    execution = ExecutionTests().execution(tmp_path)
    execution.product_results['draft'] = {'id': listing, 'revision': 1}
    upload = dict(
        id='photo', service='catalog',
        path=['/v1/seller/listings/', {'$result': 'draft/id'}, '/media'],
        photo_file='watch.png', headers={'If-Match': {'$result': 'draft/revision'},
                                        'Idempotency-Key': 'test-photo'},
        expect={'listing/revision': 2},
    )
    execution.settings['e09_journey'] = [upload]
    connection = Mock()
    connection.getresponse.return_value = Mock(
        status=201, read=Mock(return_value=b'{"listing":{"revision":2}}'))
    with patch('native.http.client.HTTPConnection', return_value=connection):
        execution.prepare_products()
    assert connection.request.call_args.args == (
        'POST', f'/v1/seller/listings/{listing}/media', image.getvalue(),
        {'If-Match': '1', 'Idempotency-Key': 'test-photo',
         'Content-Type': 'application/octet-stream', 'X-Media-Kind': 'public_photo',
         'X-Public-Safe': 'true'},
    )
    assert execution.resolve_product({'$result': 'photo/listing/revision'}) == 2

    execution.product_results.pop('photo')
    upload['photo_file'] = '../watch.png'
    with patch('native.http.client.HTTPConnection') as connect:
        with pytest.raises(Unavailable, match='catalog-photo-file'):
            execution.prepare_products()
        connect.assert_not_called()


def test_first_operator_step_grants_registered_account_and_refreshes_session(tmp_path):
    import pytest

    execution = ExecutionTests().execution(tmp_path)
    account = {'id': 'test-account', 'email': 'operator@example.test'}
    identity = {'child': Mock(), 'root': tmp_path / 'prior', 'env': {'BT_SERVICE_NAME': 'identity'}}
    execution.children['identity'] = identity
    reason = 'Authorize the initial rehearsal operator'
    execution.settings['e09_journey'] = [
        dict(id='operator', service='identity', path=['/v1/accounts/register'],
             body={}, headers={'Origin': 'http://localhost:3000'}, expect={'token_type': 'Bearer'}),
        dict(id='grant', first_operator='operator', reason=reason),
    ]
    registered = dict(account=account, token_type='Bearer', access_token='test-token')
    refreshed = dict(registered, access_token='test-current-token')
    connection = Mock()
    connection.getresponse.side_effect = [
        Mock(status=status, read=Mock(return_value=json.dumps(body).encode()),
             getheader=Mock(return_value='bt_refresh=' + 'test-refresh-' * 3))
        for status, body in ((201, registered), (200, refreshed))
    ]
    with patch('native.running', return_value=True), \
            patch('native.http.client.HTTPConnection', return_value=connection), \
            patch('native.subprocess.run', return_value=Mock(
                returncode=0, stdout=b'First platform operator granted: test-account.')) as run:
        execution.prepare_products()
    argv = run.call_args.args[0]
    assert argv[argv.index('--chdir') + 1] == str(identity['root'])
    assert argv[-4:] == ['-m', 'service_app.bootstrap_operator',
                         '--email=operator@example.test', '--reason=' + reason]
    assert run.call_args.kwargs['env'] == identity['env']
    assert run.call_args.kwargs['timeout'] == 30
    assert execution.product_headers({'Authorization': {'$bearer': 'operator'}}) == {
        'Authorization': 'Bearer test-current-token'}

    with patch('native.running', return_value=True), \
            patch('native.subprocess.run', return_value=Mock(
                returncode=0, stdout=b'First platform operator granted: test-other.')) as run, \
            patch.object(execution, 'refresh_participant') as refresh:
        with pytest.raises(Unavailable, match='first-operator-registration'):
            execution.bootstrap_operator('missing', reason)
        run.assert_not_called()
        with pytest.raises(Unavailable, match='first-operator-command'):
            execution.bootstrap_operator('operator', reason)
        refresh.assert_not_called()


def test_business_organization_is_from_live_onboarding_and_encoded(tmp_path):
    import pytest

    execution = ExecutionTests().execution(tmp_path)
    organization = '00000000-0000-4000-8000-000000000001'
    reference = {'$result': 'onboard/id'}
    execution.settings['e09_journey'] = [
        dict(id='onboard', service='identity', path=['/v1/businesses'], body={},
             expect={'state': 'active'}),
        dict(id='intake', service='orders', path=['/v1/orders/test-order/intake'],
             organization_id=reference, body={}, expect={'status': 'succeeded'}),
    ]
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.side_effect = [
        json.dumps(dict(id=organization, state='active', sample=False)).encode(),
        b'{"status":"succeeded"}',
    ]
    with patch('native.http.client.HTTPConnection', return_value=connection):
        execution.prepare_products()
    assert connection.request.call_args.args[1] == (
        '/v1/orders/test-order/intake?organization_id=' + organization)
    assert execution.organization_query('catalog', reference) == '?organization_id=' + organization

    for invalid in (organization, {'$result': 'onboard/id', 'extra': 'test'}):
        with pytest.raises(Unavailable, match='product-organization-reference'):
            execution.organization_query('orders', invalid)
    for invalid in (organization + '&override=true', '00000000-0000-4000-8000-000000000002'):
        execution.product_results['onboard']['id'] = invalid
        with pytest.raises(Unavailable, match='product-onboarded-organization'):
            execution.organization_query('orders', reference)


@pytest.mark.parametrize('assigned', [False, True])
def test_journey_uses_product_admission_to_start_payment(tmp_path, assigned):
    from contextlib import nullcontext

    execution = ExecutionTests().execution(tmp_path)
    order_id = '00000000-0000-4000-8000-000000000001'
    execution.participants['buyer'] = ('test-buyer', 'test-token', 'test-refresh', 'test-origin')
    execution.product_results['order'] = {'id': order_id, 'revision': 1}
    headers = {'Authorization': {'$bearer': 'buyer'}}
    path = ['/v1/orders/', {'$result': 'order/id'}]
    execution.settings['e09_journey'] = [
        dict(id='checkout', wait_for_payable=True, path=[*path, '/checkout'], headers=headers),
        dict(id='attempt', service='orders', path=[*path, '/payment-attempts'],
             headers={**headers, 'Idempotency-Key': 'test-attempt'},
             body={'expected_revision': {'$result': 'checkout/order/revision'}},
             expect={'status': 'succeeded'}),
    ]
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.side_effect = [
        json.dumps({'order': {'id': order_id, 'state': state, 'revision': revision},
                    'payable': payable}).encode()
        for state, revision, payable in (
            ('awaiting_notification', 1, False), ('awaiting_payment', 4, False),
            ('awaiting_payment', 5, True))
    ]
    attempt = {'id': 'test-attempt', 'order_id': order_id, 'state': 'pending'}
    payment_response = Mock(
        status=200 if assigned else 503,
        read=Mock(return_value=json.dumps(dict(status='succeeded', paid=False,
                                               attempt=attempt)).encode() if assigned else
                  b'{"error":{"code":"recovery_assignment_unavailable"}}'),
    )
    connection.getresponse.side_effect = [response, response, response, payment_response]
    outcome = nullcontext() if assigned else pytest.raises(
        Unavailable, match='orders-payment-recovery-assignment-command')
    with patch('native.http.client.HTTPConnection', return_value=connection), \
            patch('native.time.sleep'), outcome:
        execution.prepare_products()
    assert connection.request.call_count == 4
    for request in connection.request.call_args_list[:3]:
        assert request.args == ('GET', f'/v1/orders/{order_id}/checkout')
        assert request.kwargs['headers'] == {'Authorization': 'Bearer test-token'}
    assert execution.product_results['checkout']['order']['revision'] == 5
    assert ('attempt' in execution.product_results) is assigned
    if assigned:
        assert execution.payment_attempts == {'test-attempt': attempt}
        method, endpoint, body, sent_headers = connection.request.call_args.args
        assert (method, endpoint) == ('POST', f'/v1/orders/{order_id}/payment-attempts')
        assert json.loads(body) == {'expected_revision': 5}
        assert sent_headers['Idempotency-Key'] == 'test-attempt'
        assert sent_headers['Authorization'] == 'Bearer test-token'

    step = execution.settings['e09_journey'][0]
    with patch('native.time.monotonic', side_effect=[0, 31]), \
            patch('native.http.client.HTTPConnection') as connect:
        with pytest.raises(Unavailable, match='payable-order-timeout'):
            execution.wait_for_payable_order(step)
        connect.assert_not_called()


@pytest.mark.parametrize('changed_input', [
    'orders', 'module', 'manifest', 'tests', 'test-runner', 'test-config', 'packaging',
    'shared', 'contracts', 'dependencies', 'catalog',
])
def test_rollback_replays_captured_prior_invocation(tmp_path, changed_input):
    orders_changed = changed_input in {'orders', 'module', 'manifest'}
    execution = ExecutionTests().execution(tmp_path)
    prior = dict(root=tmp_path / 'prior', artifact='test-prior:orders',
                 argv=('test-prior-command', '--prior-flag'), env={'TEST_SETTING': 'test-prior'})
    execution.previous['orders'] = prior
    execution.reviewed_prior = prior['root'], {}
    execution.settings['e09_prior'] = {'artifact': 'test-prior'}
    current = tmp_path / 'current'
    execution.releases['test-current'] = current
    execution.children['orders'] = dict(child=Mock(pid=123), start='test-current',
                                        root=current, artifact='test-current:orders')
    from native import orders_executable_digest

    inputs = {
        'orders': 'services/orders/runtime/service_app/orders_kernel.py',
        'module': 'services/orders/modules/allocation/routes.py',
        'manifest': 'services/orders/modules/allocation/module.json',
        'tests': 'services/orders/modules/allocation/tests/test_routes.py',
        'test-runner': 'services/orders/runtime/run_tests.py',
        'test-config': 'services/orders/runtime/conftest.py',
        'packaging': 'services/orders/runtime/package_contracts.py',
        'shared': 'packages/runtime/src/runtime.py',
        'contracts': 'contracts/bt_contracts/orders/models.py',
        'dependencies': 'runtime/site-packages/dependency.py',
        'catalog': 'services/catalog/runtime/service_app/main.py',
    }
    for root in (prior['root'], current):
        for label, name in inputs.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            content = 'test-current' if root == current and label == changed_input else 'test-prior'
            path.write_text(f'VERSION = {content!r}\n')
        # Prior-only runtime layout and generated files must not affect the comparison.
        if root == prior['root']:
            (root / 'runtime/bin').mkdir()
            (root / 'runtime/bin/python3').write_bytes(b'test-prior-interpreter')
            (root / 'services/orders/runtime/service_app/generated.py').write_bytes(b'test-generated')
        tracked = b'\0'.join(name.encode() for name in inputs.values()
                             if name.startswith('services/orders/')) + b'\0'
        with patch('native.subprocess.run', return_value=Mock(stdout=tracked)) as git:
            execution.orders_executables[root] = orders_executable_digest(
                root, execution.services['orders']['factory'], 'test-source')
        assert git.call_args.args[0][:5] == [
            'git', 'ls-tree', '-rz', '--name-only', 'test-source']
    execution.acknowledged_callback_id = 'test-recovered'
    snapshot = {'receipts': [
        {'operation_id': 'test-baseline', 'attempt': {'order_id': 'test-baseline-order'}},
        {'operation_id': 'test-recovered', 'attempt': {'order_id': 'test-recovered-order'}},
    ]}
    with patch.object(execution, 'environment', side_effect=AssertionError), \
            patch.object(execution, 'invocation', side_effect=AssertionError), \
            patch.object(execution, 'isolated'), patch.object(execution, 'ready'), \
            patch.object(execution, 'stop') as stop, patch.object(execution, 'authority', return_value=True) as authority, \
            patch.object(execution, 'reads', return_value=snapshot), patch('native.running', return_value=True), \
            patch.object(execution, 'spawn', return_value={'child': Mock(pid=124), 'start': 'test-prior'}) as spawn:
        result = execution.call('rollback', {'candidate': 'test-current'})
    authority.assert_called_once_with('test-recovered-order')
    stop.assert_called_once_with('orders')
    assert (result['before_orders_executable'] != result['orders_executable']) is orders_changed
    spawn.assert_called_once_with('orders', prior['argv'], tmp_path, prior['env'])
    assert result['artifact'] == prior['artifact']
    assert result['before_artifact'] == 'test-current:orders'
    assert result['before_orders_executable'] == execution.orders_executables[current]
    assert result['orders_executable'] == execution.orders_executables[prior['root']]


@pytest.mark.parametrize('failure', ['isolation', 'artifact', 'invocation'])
def test_replace_validates_before_stopping_owned_process(tmp_path, failure):
    execution = ExecutionTests().execution(tmp_path)
    before = {'child': Mock(pid=123)}
    execution.children['orders'] = before
    release = tmp_path / 'release'
    execution.releases['test-current'] = release
    execution.images[release] = Mock(closed=failure == 'artifact')
    with patch('native.running', return_value=True), \
            patch.object(execution, 'isolated', side_effect=(
                Unavailable('test-isolation') if failure == 'isolation' else None)), \
            patch.object(execution, 'invocation', side_effect=Unavailable('test-invocation')), \
            patch.object(execution, 'stop') as stop, patch.object(execution, 'launch') as launch:
        reason = 'replacement-release-artifact' if failure == 'artifact' else 'test-' + failure
        with pytest.raises(Unavailable, match=reason):
            execution.replace('orders', release, 'test-current:orders')
        stop.assert_not_called()
        launch.assert_not_called()
    assert execution.children['orders'] is before


def test_assignment_shortcut_fails_before_product_requests(tmp_path):
    execution = ExecutionTests().execution(tmp_path)
    execution.settings['e09_journey'] = [
        dict(id='assignment', assign_payment_recovery={'$result': 'order/id'}),
    ]
    with patch('native.http.client.HTTPConnection') as connect:
        with pytest.raises(Unavailable, match='orders-payment-recovery-assignment-command'):
            execution.prepare_products()
    connect.assert_not_called()


def test_watermark_journey_uses_live_subject_and_product_request(tmp_path):
    execution = ExecutionTests().execution(tmp_path)
    execution.product_results['registered'] = {'account': {'id': 'test-subject'}}
    execution.participants['registered'] = ('test-subject', 'test-token', 'test-refresh', 'test-origin')
    execution.settings['e09_watermark_journey'] = [{
        'id': 'delete', 'service': 'identity', 'method': 'DELETE',
        'path': ['/v1/data/', {'$result': 'registered/account/id'}],
        'body': {}, 'headers': {'Authorization': {'$bearer': 'registered'},
                                'Idempotency-Key': 'test-deletion'},
        'expect': {'status': 'accepted'},
    }]
    connection = Mock()
    connection.getresponse.return_value = Mock(
        status=202, read=Mock(return_value=b'{"status":"accepted"}'))
    def refresh(name):
        assert name == 'registered'
        connection.request.assert_not_called()
        execution.participants[name] = ('test-subject', 'test-fresh', 'test-refresh', 'test-origin')

    with patch('native.http.client.HTTPConnection', return_value=connection), \
            patch.object(execution, 'refresh_participant', side_effect=refresh) as refresh_session:
        execution.prepare_products('e09_watermark_journey')
    refresh_session.assert_called_once_with('registered')
    connection.request.assert_called_once_with(
        'DELETE', '/v1/data/test-subject', b'{}',
        {'Authorization': 'Bearer test-fresh', 'Idempotency-Key': 'test-deletion',
         'Content-Type': 'application/json'},
    )
    assert execution.product_results['delete']['status'] == 'accepted'


def test_receipt_wait_observes_later_payment_event_without_using_checkout(tmp_path):
    execution = ExecutionTests().execution(tmp_path)
    pending = {'inbox': [{'operation_id': 'test-earlier'}]}
    acknowledged = {'inbox': [{'operation_id': 'test-confirmed'}]}
    with patch.object(execution, 'reads', return_value=acknowledged), patch('native.time.sleep'):
        assert execution.await_payment_inbox(pending, {'test-confirmed'}) is acknowledged
    with patch.object(execution, 'reads') as read, \
            patch('native.time.monotonic', side_effect=[0, 16]):
        with pytest.raises(Unavailable, match='communications-payment-confirmed-delivery'):
            execution.await_payment_inbox(pending, {'test-confirmed'})
        read.assert_not_called()


@pytest.mark.parametrize('field', ['receipts', 'journal', 'custody', 'outbox'])
def test_recovery_rejects_record_changes_while_inbox_is_pending(tmp_path, field):
    tests = ExecutionTests()
    execution = tests.execution(tmp_path)
    baseline = tests.bind_recovery_attempt(execution)
    execution.children['orders'] = dict(root=tmp_path, artifact='test-artifact')
    reference = dict(operation_id='test-event')
    original = {name: [dict(reference, revision=1)]
                for name in ('receipts', 'journal', 'custody', 'outbox')}
    original['receipts'][0]['attempt'] = {'id': 'test-attempt', 'order_id': 'test-order'}
    original['inbox'] = []
    changed = dict(original, **{field: [dict(original[field][0], revision=2)]})

    with patch('native.http.client.HTTPConnection') as connect, \
            patch.object(execution, 'reads', side_effect=[baseline, original, changed]), \
            patch('native.time.sleep'), patch.object(execution, 'replace', return_value={
                'before_artifact': 'test-artifact', 'artifact': 'test-artifact'}) as replace:
        connect.return_value.getresponse.return_value = Mock(
            status=200, read=Mock(return_value=(
                b'{"status":"succeeded","paid":true,"attempt":'
                b'{"state":"confirmed","id":"test-attempt","order_id":"test-order"}}')))
        with pytest.raises(Unavailable, match='retained-product-' + field):
            execution.recover_command('test-artifact')

    assert execution.acknowledged_callback_id == 'test-event'
    calls = connect.return_value.request.call_args_list
    assert len(calls) == 2 and calls[0] == calls[1]
    connect.return_value.getresponse.assert_called_once()
    replace.assert_called_once_with('orders', tmp_path, 'test-artifact')


def test_prior_python_command_uses_reviewed_runtime_and_isolated_imports(tmp_path):
    from native import PRIOR_PYTHON_ENTRY

    run = tmp_path / 'run'
    run.mkdir()
    execution = ExecutionTests().execution(run)
    prior = tmp_path / 'prior'
    from native import SERVICE_MANIFEST

    manifest = prior / SERVICE_MANIFEST
    manifest.parent.mkdir(parents=True)
    services = [dict(item) for item in execution.services.values()]
    next(item for item in services if item['name'] == 'orders')['factory'] = 'prior_app:create_app'
    raw = json.dumps({'schema_version': 1, 'services': services}).encode()
    manifest.write_bytes(raw)
    inventory = {SERVICE_MANIFEST: hashlib.sha256(raw).hexdigest()}
    execution.prior_services = execution.prior_startup_services(prior, inventory)
    execution.reviewed_prior = prior, inventory
    manifest.write_bytes(raw + b' ')
    with pytest.raises(Unavailable, match='reviewed-prior-service-manifest'):
        execution.prior_startup_services(prior, inventory)
    scoped = execution.settings['services']['orders']['env']
    scoped.update(LD_LIBRARY_PATH='/tmp/test-library', PYTHONHOME='/tmp/test-python')
    env = execution.environment('orders', prior)
    invocation = execution.invocation('orders', prior, 'test-prior:orders', env)
    command = invocation['argv']
    interpreter = str(prior / 'runtime/bin/python3')
    assert command[command.index('--') + 1:] == (
        interpreter, '-I', '-S', '-c', PRIOR_PYTHON_ENTRY, str(prior),
        env['PYTHONPATH'], 'uvicorn', 'prior_app:create_app',
        '--factory', '--host', '127.0.0.1', '--port', str(execution.services['orders']['port']),
    )
    assert env['PATH'].split(':')[0] == str(prior / 'runtime/bin')
    assert 'LD_LIBRARY_PATH' not in env and 'PYTHONHOME' not in env
    assert execution.python_command(prior, env, 'service_app.bootstrap_operator')[-1] == (
        'service_app.bootstrap_operator')
    assert execution.python_command(tmp_path / 'candidate', {}, 'uvicorn') == [
        execution.settings['python'], '-m', 'uvicorn']


def test_callback_reference_survives_failed_reconciliation_read(tmp_path):
    tests = ExecutionTests()
    execution = tests.execution(tmp_path)
    baseline = tests.bind_recovery_attempt(execution)
    execution.children['orders'] = dict(root=tmp_path, artifact='test-artifact')
    with patch('native.http.client.HTTPConnection') as connect, \
            patch.object(execution, 'reads', side_effect=[
                baseline, Unavailable('durable-custody-operation')]), \
            patch('native.time.sleep'), patch.object(execution, 'replace', return_value={
                'before_artifact': 'test-artifact', 'artifact': 'test-artifact'}) as replace:
        connection = connect.return_value
        checks = iter((False, True))

        def acknowledge(*args):
            connection.request.assert_called_once()
            connection.close.assert_not_called()
            connection.getresponse.assert_not_called()
            return next(checks)

        execution.callback_acknowledged.side_effect = acknowledge
        connect.return_value.getresponse.return_value = Mock(
            status=200, read=Mock(return_value=(
                b'{"status":"succeeded","paid":true,"attempt":'
                b'{"state":"confirmed","id":"test-attempt","order_id":"test-order"}}')))
        with pytest.raises(Unavailable, match='durable-custody-operation'):
            execution.recover_command('test-artifact')

    assert execution.callback_acknowledged.call_args_list == [
        unittest.mock.call('test-event', 'test-attempt', 'test-order')] * 2
    assert execution.acknowledged_callback_id == 'test-event'
    calls = connect.return_value.request.call_args_list
    assert len(calls) == 2 and calls[0] == calls[1]
    connect.return_value.getresponse.assert_called_once()
    replace.assert_called_once_with('orders', tmp_path, 'test-artifact')


def test_callback_timeout_closes_unread_connection_without_restarting(tmp_path):
    tests = ExecutionTests()
    execution = tests.execution(tmp_path)
    baseline = tests.bind_recovery_attempt(execution)
    execution.children['orders'] = dict(root=tmp_path, artifact='test-artifact')
    execution.callback_acknowledged.return_value = False

    with patch('native.http.client.HTTPConnection') as connect, \
            patch.object(execution, 'reads', return_value=baseline), \
            patch('native.time.monotonic', side_effect=[0, 1, 11]), \
            patch('native.time.sleep'), patch.object(execution, 'replace') as replace:
        with pytest.raises(Unavailable, match='durably-acknowledged-product-command'):
            execution.recover_command('test-artifact')

    execution.callback_acknowledged.assert_called_once_with('test-event', 'test-attempt', 'test-order')
    connect.return_value.close.assert_called_once_with()
    connect.return_value.getresponse.assert_not_called()
    replace.assert_not_called()
    assert execution.acknowledged_callback_id is None


@pytest.mark.parametrize('failure', [None, 'digest', 'revision', 'runtime', 'permissions', 'size'])
def test_repeat_registers_original_sealed_bytes_without_building(tmp_path, failure):
    import os
    import tarfile

    from native import orders_executable_digest, seal_release

    run = tmp_path / 'run'
    run.mkdir()
    execution = ExecutionTests().execution(run)
    source = tmp_path / 'export'
    tracked = 'services/orders/runtime/service_app/main.py'
    orders = source / tracked
    orders.parent.mkdir(parents=True)
    orders.write_text('VERSION = "test-primary"\n')
    archive = tmp_path / 'candidate.tar'
    fingerprint = execution.candidate_runtime.fingerprint
    with seal_release(source, 'test-original-revision', fingerprint)[0] as image:
        image.seek(0)
        original = image.read()
    archive.write_bytes(original)
    archive.chmod(0o644 if failure == 'permissions' else 0o400)
    digest = hashlib.sha256(original).hexdigest()
    execution.settings['e09_candidate'] = {
        'schema_version': 1, 'archive': str(archive),
        'sha256': '0' * 64 if failure == 'digest' else digest,
    }
    revision = 'test-other-revision' if failure == 'revision' else 'test-original-revision'
    runtime = execution.candidate_runtime
    if failure == 'runtime':
        from dataclasses import replace
        runtime = replace(runtime, fingerprint='test-changed-runtime')
    with patch.object(execution, 'isolated'), \
            patch.object(execution, 'build_release') as build, \
            patch('native.candidate_runtime', return_value=runtime), \
            patch('native.retain_archive') as retain, \
            patch('native.subprocess.run', return_value=Mock(stdout=tracked.encode() + b'\0')), \
            patch('native.ARCHIVE_LIMIT', 1 if failure == 'size' else len(original)):
        try:
            if failure:
                reason = {
                    'digest': 'repeat-release-archive-hash',
                    'revision': 'repeat-release-source-revision',
                    'runtime': 'repeat-release-runtime-hash',
                    'permissions': 'private-repeat-release-archive',
                    'size': 'bounded-release-archive',
                }[failure]
                with pytest.raises(Unavailable, match=reason):
                    execution.build({'source_revision': revision})
                assert not execution.releases and not execution.images
            else:
                result = execution.build({'source_revision': revision})
                assert result['candidate'] == digest
                assert result['archive_mode'] == 'reused'
                assert result['artifacts']['orders'] == digest + ':orders'
                target = execution.releases[digest]
                assert execution.orders_executables[target] == orders_executable_digest(
                    source, execution.services['orders']['factory'], revision)
                archive.unlink()
                with open(f'/proc/self/fd/{execution.images[target].fileno()}', 'rb') as stream:
                    assert stream.read() == original
                    stream.seek(0)
                    with tarfile.open(fileobj=stream) as sealed:
                        assert sealed.extractfile('./' + tracked).read() == orders.read_bytes()
                with pytest.raises(PermissionError):
                    os.ftruncate(execution.images[target].fileno(), 0)
            build.assert_not_called()
            retain.assert_not_called()
        finally:
            execution.close()


@pytest.mark.parametrize('component', ['interpreter', 'stdlib', 'site', 'node', 'store'])
def test_runtime_fingerprint_binds_bytes_at_unchanged_paths(tmp_path, component):
    import os

    from native import candidate_runtime

    venv = tmp_path / 'runtime'
    inputs = {
        'interpreter': venv / 'bin/python',
        'stdlib': tmp_path / 'stdlib/runtime.py',
        'site': venv / 'lib/python3.11/site-packages/dependency.py',
        'node': tmp_path / 'test-node',
        'store': tmp_path / STORE_PATH / 'dependency/index.js',
    }
    for path in inputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test-original')
    (venv / 'pyvenv.cfg').write_text('test-config')
    probe = Mock(stdout=f"(3, 11)\n{inputs['stdlib'].parent}\n")
    with patch('native.NODE', str(inputs['node'])), \
            patch('native.subprocess.run', return_value=probe), \
            patch('native.os.statvfs', return_value=Mock(f_flag=os.ST_RDONLY)):
        initial = candidate_runtime(str(inputs['interpreter']), tmp_path)
        assert candidate_runtime(str(inputs['interpreter']), tmp_path) == initial
        inputs[component].write_bytes(b'test-replaced')
        assert candidate_runtime(str(inputs['interpreter']), tmp_path).fingerprint != initial.fingerprint


@pytest.mark.parametrize('failure', [None, 'denied', 'not-sample', 'bad-code', 'oversized',
                                    'other-participant', 'other-challenge', 'general-get'])
def test_contact_simulator_code_is_bound_to_identity_verification(tmp_path, failure):
    execution = ExecutionTests().execution(tmp_path)
    challenge_id = '00000000-0000-4000-8000-000000000001'
    path = '/v1/contacts/challenges/' + challenge_id
    code = '012345'
    execution.participants['buyer'] = ('test-buyer', 'test-buyer-token', 'test-refresh', 'test-origin')
    execution.participants['other'] = ('test-other', 'test-other-token', 'test-refresh', 'test-origin')
    execution.product_results['challenge'] = {
        'id': challenge_id, 'state': 'pending', 'delivery_mode': 'sample_simulator',
    }
    read = dict(id='code', contact_challenge={'$result': 'challenge'}, participant='buyer')
    verify = dict(id='verification', service='identity',
                  path=[path + '/verify'],
                  headers={'Authorization': {'$bearer': 'buyer'}, 'Idempotency-Key': 'test-verify'},
                  body={'code': {'$contact_code': 'code'}}, expect={'email_verified': True})
    if failure == 'other-participant':
        verify['headers']['Authorization'] = {'$bearer': 'other'}
    if failure == 'other-challenge':
        verify['path'] = [path[:-1] + '2/verify']
    if failure == 'general-get':
        verify.update(method='GET', path=[path + '/sample-code'], body={})
    execution.settings['e09_journey'] = [verify] if failure == 'general-get' else [read, verify]

    reply = json.dumps({'sample': failure != 'not-sample',
                        'code': 'invalid' if failure == 'bad-code' else code}).encode()
    read_connection, verify_connection = Mock(), Mock()
    read_connection.getresponse.return_value = Mock(
        status=403 if failure == 'denied' else 200,
        read=Mock(return_value=b' ' * 4097 if failure == 'oversized' else reply))
    verify_connection.getresponse.return_value = Mock(
        status=200, read=Mock(return_value=b'{"email_verified":true}'))
    with patch('native.http.client.HTTPConnection',
               side_effect=[read_connection, verify_connection]) as connect:
        if failure:
            reason = {
                'denied': 'contact-simulator-read',
                'not-sample': 'contact-simulator-result',
                'bad-code': 'contact-simulator-result',
                'oversized': 'bounded-contact-simulator-result',
                'other-participant': 'contact-simulator-verification-scope',
                'other-challenge': 'contact-simulator-verification-scope',
                'general-get': 'product-command-method',
            }[failure]
            with pytest.raises(Unavailable, match=reason):
                execution.prepare_products()
            verify_connection.request.assert_not_called()
        else:
            execution.prepare_products()
            method, target, payload, headers = verify_connection.request.call_args.args
            assert (method, target) == ('POST', path + '/verify')
            assert json.loads(payload) == {'code': code}
            assert headers['Idempotency-Key'] == 'test-verify'
            assert headers['Authorization'] == 'Bearer test-buyer-token'
            assert execution.product_results['verification'] == {'email_verified': True}

    if failure == 'general-get':
        connect.assert_not_called()
    else:
        assert connect.call_args_list[0].args == ('127.0.0.1', execution.services['identity']['port'])
        read_connection.request.assert_called_once_with(
            'GET', path + '/sample-code', headers={'Authorization': 'Bearer test-buyer-token'})
        read_connection.close.assert_called_once_with()
    assert code not in json.dumps(execution.product_results)


@pytest.mark.parametrize('field', ['receipts', 'journal', 'custody', 'outbox'])
def test_baseline_rejects_record_changes_before_inbox_delivery(tmp_path, field):
    execution = ExecutionTests().execution(tmp_path)
    reference = {'operation_id': 'test-baseline'}
    original = {
        'receipts': [dict(reference, retained_quote={'buyer_fee_minor': 10,
                                                   'shipping_minor': 5, 'payable_minor': 100})],
        'journal': [dict(reference, effect_count=1)],
        'custody': [dict(reference, revision=1)],
        'outbox': [dict(reference, event_id='test-event')],
        'inbox': [],
    }
    changes = {
        'receipts': {'retained_quote': {'buyer_fee_minor': 9, 'shipping_minor': 6,
                                        'payable_minor': 100}},
        'journal': {'effect_count': 2},
        'custody': {'revision': 2},
        'outbox': {'event_id': 'test-different-event'},
    }
    changed = dict(original, inbox=[reference])
    changed[field] = [dict(original[field][0], **changes[field])]

    with patch.object(execution, 'reads', side_effect=[original, changed]), \
            patch('native.time.sleep'):
        with pytest.raises(Unavailable, match='retained-product-' + field):
            execution.call('authoritative-reads', {})

    assert execution.partial_measurements == original


@pytest.mark.parametrize(('release', 'additive', 'endpoint'), [
    ('prior', True, '/health/e09-ready'),
    ('prior', False, '/health/ready'),
    ('candidate', True, '/health/ready'),
])
def test_readiness_with_forward_migrations(tmp_path, release, additive, endpoint):
    execution = ExecutionTests().execution(tmp_path)
    prior_root = tmp_path / 'prior'
    execution.reviewed_prior = prior_root, {}
    prior = {'test-original': 'test-original-checksum'}
    candidate = dict(prior)
    if additive:
        candidate['test-addition'] = 'test-addition-checksum'
    execution.compatible_ledgers['orders'] = prior, candidate
    env = execution.environment('orders', tmp_path)
    execution.children['orders'] = {'root': tmp_path / release, 'env': env}
    rows = [dict(step_id=name, checksum=checksum) for name, checksum in candidate.items()]
    with patch('native.urllib.request.build_opener') as build_opener, \
            patch('restore.measure', return_value=rows) as measure:
        opener = build_opener.return_value
        opener.open.return_value.__enter__.return_value.status = 200
        execution.ready('orders')
        opener.open.assert_called_once_with('http://127.0.0.1:8105' + endpoint, timeout=1)
        if release == 'prior':
            measure.assert_called_once_with(['-d', env['BT_DATABASE_URL']],
                                            'SELECT step_id, checksum FROM public.migration_ledger')
            measure.return_value = []
            with pytest.raises(Unavailable, match='orders-candidate-migration-ledger'):
                execution.ready('orders')
        else:
            measure.assert_not_called()


@pytest.mark.parametrize('candidate', [{}, {'test-original': 'test-modified-checksum'}])
def test_changed_or_removed_prior_migration_blocks_launch(tmp_path, candidate):
    execution = ExecutionTests().execution(tmp_path)
    with patch('restore.measure') as measure:
        with pytest.raises(Unavailable, match='orders-incompatible-prior-migrations'):
            execution.verify_compatible_ledger(
                'orders', {}, {'test-original': 'test-original-checksum'}, candidate)
    measure.assert_not_called()


@pytest.mark.parametrize(('rows', 'status'), [
    ([('test-old', 'test-checksum'), ('test-added', 'test-new-checksum')], 200),
    ([('test-old', 'test-checksum'), ('test-added', 'test-wrong-checksum')], 503),
    ([('test-old', 'test-checksum')], 503),
    (None, 503),
])
def test_forward_readiness_checks_the_running_prior_application_pool(tmp_path, monkeypatch, rows, status):
    import asyncio
    from contextlib import asynccontextmanager
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import FastAPI, HTTPException

    from native import PRIOR_FORWARD_ENTRY, PRIOR_PYTHON_PATHS

    execution = ExecutionTests().execution(tmp_path)
    prior = tmp_path.parent / 'prior'
    execution.reviewed_prior = prior, {}
    execution.prior_services = execution.services
    old = {'test-old': 'test-checksum'}
    candidate = dict(old, **{'test-added': 'test-new-checksum'})
    execution.compatible_ledgers['orders'] = old, candidate
    invocation = execution.invocation(
        'orders', prior, 'test-prior:orders', execution.environment('orders', prior))
    argv = invocation['argv']
    entry = argv.index('-c') + 1
    assert argv[entry] == PRIOR_FORWARD_ENTRY
    assert json.loads(argv[-1]) == candidate

    app = FastAPI()
    fetch = AsyncMock(return_value=rows)

    @asynccontextmanager
    async def acquire():
        if rows is None:
            raise OSError('test-pool-unavailable')
        yield SimpleNamespace(fetch=fetch)

    app.state.pool = SimpleNamespace(acquire=acquire)
    factory = SimpleNamespace(create_app=lambda: app)
    monkeypatch.setitem(sys.modules, 'bt_runtime.app.main', factory)
    with patch.object(sys, 'argv', ['-c', *argv[entry + 1:]]), patch('uvicorn.run') as serve:
        exec(argv[entry].removeprefix(PRIOR_PYTHON_PATHS), {'sys': sys})
    serve.assert_called_once_with(app, host='127.0.0.1', port=8105)
    route = next(route for route in app.routes if route.path == '/health/e09-ready')
    if status == 200:
        assert asyncio.run(route.endpoint()) == {'status': 'ready'}
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(route.endpoint())
        assert error.value.status_code == status
    if rows is not None:
        fetch.assert_awaited_once_with('SELECT step_id, checksum FROM public.migration_ledger')
