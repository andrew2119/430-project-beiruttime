import importlib.util
from importlib.machinery import PathFinder
import json
import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('native', Path(__file__).resolve().parents[3] / 'scripts/native-stack.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(native, 'admission')
        self.guard = guard.start()
        self.addCleanup(guard.stop)
        for target in ('members', 'os.kill', 'os.killpg'):
            parent, _, attribute = target.rpartition('.')
            owner = native.os if parent else native
            double = patch.object(owner, attribute, return_value=[] if target == 'members' else None)
            replacement = double.start()
            self.addCleanup(double.stop)
            if parent:
                self.addCleanup(replacement.assert_not_called)

    def test_plan_is_pure(self):
        with patch.object(native.subprocess, 'Popen', side_effect=AssertionError), patch.object(native.socket, 'socket', side_effect=AssertionError):
            result = native.plan(native.select(','.join(s['name'] for s in native.MANIFEST['services'])))
        self.assertEqual(len(result['services']), 10)
        self.assertEqual(len(set(result['databases'])), 9)
        self.assertIn('bt_service_ops', result['databases'])
        self.assertEqual(result['host'], '127.0.0.1')

    def test_selection(self):
        for value in ('', 'identity,identity', 'other'):
            with self.assertRaises(ValueError):
                native.select(value)

    def test_environment_is_separate(self):
        cap = {'python': '/tmp/python', 'postgres_bin': '/tmp/bin'}
        with patch.dict(native.os.environ, {'OTHER_OWNER_PASSWORD': 'secret', 'BT_DATABASE_URL': 'shared'}):
            service = native.MANIFEST['services'][8]
            owner = native.environment(cap, Path('/tmp/run'), service, True)
            runtime = native.environment(cap, Path('/tmp/run'), service)
            web = native.environment(cap, Path('/tmp/run'), native.MANIFEST['services'][-1])
        self.assertIn('bt_service_ops_owner:', owner['BT_DATABASE_URL'])
        self.assertNotIn('_owner', runtime['BT_DATABASE_URL'])
        self.assertNotIn('BT_DATABASE_URL', web)
        self.assertNotIn('OTHER_OWNER_PASSWORD', runtime)
        self.assertEqual(runtime['BT_ORDERS_URL'], 'http://127.0.0.1:8105')
        self.assertEqual(runtime['BT_ALLOWED_WEB_ORIGINS'], ','.join(native.MANIFEST['origins']))

    def test_catalog_module_import_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = root / 'services/catalog'
            listings = service / 'modules/listings'
            listings.mkdir(parents=True)
            (service / 'modules/__init__.py').write_text('')
            (listings / '__init__.py').write_text('')
            (listings / 'repository.py').write_text('value = 1\n')
            catalog = native.select('catalog')[0]
            with patch.object(native, 'ROOT', root):
                for owner in (False, True):
                    env = native.environment(
                        {'python': '/tmp/python', 'postgres_bin': '/tmp/bin'},
                        root / 'run', catalog, owner)
                    paths = env['PYTHONPATH'].split(native.os.pathsep)
                    self.assertIn(str(service / 'runtime'), paths)
                    modules = PathFinder.find_spec('modules', paths)
                    self.assertIsNotNone(modules)
                    package = PathFinder.find_spec(
                        'modules.listings', modules.submodule_search_locations)
                    self.assertIsNotNone(package)
                    repository = PathFinder.find_spec(
                        'modules.listings.repository', package.submodule_search_locations)
                    self.assertEqual(repository.origin, str(listings / 'repository.py'))

    def test_override_refused(self):
        with self.assertRaises(ValueError):
            native.environment({'python': '/tmp/python', 'postgres_bin': '/tmp/bin', 'environment': {'PGHOST': 'shared'}}, Path('/tmp/run'))

    def test_reused_pid_is_not_owned(self):
        with patch.object(native, 'ticks', return_value='new'), patch.object(native.os, 'getpgid', side_effect=AssertionError):
            self.assertFalse(native.owned({'pid': 42, 'start_ticks': 'old'}))

    def test_stop_does_not_signal_foreign_process(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            ledger = {'processes': [{'pid': 42, 'start_ticks': 'old'}]}
            with patch.object(native, 'owned', return_value=False), patch.object(native.os, 'killpg', side_effect=AssertionError):
                native.stop(run, ledger)
            self.assertEqual(json.loads((run / 'ledger.json').read_text())['state'], 'stopped')

    def test_occupied_port_records_failure_without_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'new'
            with patch.object(native, 'available', side_effect=OSError(errno.EADDRINUSE, 'Address already in use')), patch.object(native.subprocess, 'Popen', side_effect=AssertionError):
                with self.assertRaises(OSError):
                    native.start(run, native.MANIFEST['services'], {})
            ledger = json.loads((run / 'ledger.json').read_text())
            self.assertEqual(ledger['state'], 'failed')
            self.assertEqual(ledger['processes'], [])
            self.assertEqual(ledger['failure'], {
                'phase': 'port-precheck', 'port': 54329,
                'errno': errno.EADDRINUSE, 'reason': '[Errno 98] Address already in use'})
            self.assertEqual(run.stat().st_mode & 0o777, 0o700)

    def test_time_wait_port_is_available(self):
        # Model the kernel refusing a stale connection unless reuse is enabled.
        probe = Mock()
        probe.__enter__ = Mock(return_value=probe)
        probe.__exit__ = Mock(return_value=False)
        reused = False

        def reuse(level, option, value):
            nonlocal reused
            self.assertEqual((level, option, value),
                             (native.socket.SOL_SOCKET, native.socket.SO_REUSEADDR, 1))
            reused = True

        def bind(address):
            self.assertEqual(address, ('127.0.0.1', 54329))
            if not reused:
                raise OSError(errno.EADDRINUSE, 'Port held in TIME_WAIT')

        probe.setsockopt.side_effect = reuse
        probe.bind.side_effect = bind
        with patch.object(native.socket, 'socket', return_value=probe):
            native.available(54329)
        probe.listen.assert_called_once_with(1)

    def test_live_listener_or_bound_port_is_refused(self):
        for stage in ('bind', 'listen'):
            with self.subTest(stage=stage):
                probe = Mock()
                probe.__enter__ = Mock(return_value=probe)
                probe.__exit__ = Mock(return_value=False)
                getattr(probe, stage).side_effect = OSError(errno.EADDRINUSE, 'Port in use')
                with patch.object(native.socket, 'socket', return_value=probe):
                    with self.assertRaises(OSError):
                        native.available(54329)

    def test_capability_requires_installed_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cap.json'
            path.write_text(json.dumps({'schema_version': 1, 'batch_id': 'bounded'}))
            self.guard.side_effect = ValueError('missing admission')
            with self.assertRaises(ValueError):
                native.capability(path)

    def test_failed_start_preserves_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'new'
            cap = {'python': '/tmp/python', 'postgres_bin': '/tmp/bin'}
            with patch.object(native, 'available'), patch.object(native.subprocess, 'check_output', side_effect=OSError), patch.object(native.os, 'killpg', side_effect=AssertionError):
                with self.assertRaises(OSError):
                    native.start(run, [], cap)
            self.assertEqual(json.loads((run / 'ledger.json').read_text())['state'], 'failed')

    def test_readiness_exit_is_failure(self):
        with patch.object(native.urllib.request, 'urlopen', side_effect=AssertionError):
            with self.assertRaises(RuntimeError):
                native.wait_ready('http://127.0.0.1:8101/health/ready', Mock(poll=lambda: 1))

    def test_successful_start_uses_owned_initializer_and_owner_only_for_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'new'
            calls = []
            child = Mock(pid=123, wait=Mock(return_value=0), poll=Mock(return_value=None))
            child.diagnostic_reader.is_alive.return_value = False
            def launch(folder, ledger, name, command, env):
                calls.append((name, command, env))
                ledger['processes'].append({'name': name, 'pid': 123, 'start_ticks': '1'})
                child.poll.return_value = None if name in ('database', 'database-restricted') else 0
                return child
            cap = {'python': '/tmp/python', 'postgres_bin': '/tmp/bin'}
            with patch.object(native, 'available'), patch.object(native, 'launch', side_effect=launch), patch.object(native.subprocess, 'check_output', return_value=b'postgres (PostgreSQL) 17.6'), patch.object(native.subprocess, 'run', return_value=Mock(returncode=0)), patch.object(native, 'wait_ready'), patch.object(native, 'restrict_auth'), patch.object(native, 'owned', return_value=False), patch.object(native, 'supervise'):
                native.start(run, [native.MANIFEST['services'][0], native.MANIFEST['services'][-1]], cap)
            initialization = next(c for c in calls if c[1][0].endswith('/initdb'))
            self.assertIn('--encoding=UTF8', initialization[1])
            self.assertIn('--no-locale', initialization[1])
            self.assertIn('--auth-host=reject', initialization[1])
            bootstrap = next(c for c in calls if c[0] == 'database')
            self.assertEqual(bootstrap[1][bootstrap[1].index('-h') + 1], '')
            restricted = next(c for c in calls if c[0] == 'database-restricted')
            self.assertEqual(restricted[1][restricted[1].index('-h') + 1], '127.0.0.1')
            initializer = next(c for c in calls if 'bash' in c[1])
            self.assertEqual(initializer[2]['PGHOST'], str(run))
            self.assertEqual(initializer[2]['PGPORT'], '54329')
            self.assertEqual(len([k for k in initializer[2] if k.endswith('_OWNER_PASSWORD')]), 9)
            migration = next(c for c in calls if 'service_app.migrate' in c[1])
            self.assertIn('_owner:', migration[2]['BT_DATABASE_URL'])
            runtime = next(c for c in calls if c[0] == 'identity')
            self.assertNotIn('_owner:', runtime[2]['BT_DATABASE_URL'])
            web = next(c for c in calls if c[0] == 'web')
            self.assertNotIn('BT_DATABASE_URL', web[2])
            self.assertEqual(web[1], [
                'node', 'web/node_modules/next/dist/bin/next', 'start', 'web',
                '--hostname', '127.0.0.1', '--port', '3000'])
            self.assertFalse((run / 'web').exists())
            self.assertEqual(json.loads((run / 'ledger.json').read_text())['state'], 'ready')

    def test_interruption_cleans_owned_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'new'
            cap = {'python': '/tmp/python', 'postgres_bin': '/tmp/bin'}
            with patch.object(native, 'available'), patch.object(native.subprocess, 'check_output', side_effect=KeyboardInterrupt), patch.object(native, 'stop', wraps=native.stop) as cleanup:
                with self.assertRaises(KeyboardInterrupt):
                    native.start(run, [], cap)
                cleanup.assert_called_once()
            self.assertEqual(json.loads((run / 'ledger.json').read_text())['state'], 'failed')

    def test_disappearing_process_does_not_abort_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(native, 'owned', return_value=True), patch.object(native.os, 'killpg', side_effect=ProcessLookupError), patch.object(native, 'members', return_value=[]), patch.object(native.time, 'monotonic', side_effect=[0, 11, 12, 18]):
                native.stop(Path(directory), {'processes': [{'pid': 123}]})

    def test_interruption_after_launch_signals_only_owned_group(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'new'
            cap = {'python': '/tmp/python', 'postgres_bin': '/tmp/bin'}
            def launched(folder, ledger, name, command, env):
                ledger['processes'].append({'name': name, 'pid': 123, 'start_ticks': '1'})
                return Mock(wait=Mock(side_effect=KeyboardInterrupt), diagnostic_reader=Mock(is_alive=Mock(return_value=False)))
            with patch.object(native, 'available'), patch.object(native.subprocess, 'check_output', return_value=b'postgres (PostgreSQL) 17.6'), patch.object(native, 'launch', side_effect=launched), patch.object(native, 'owned', side_effect=[True, False, False, False, False]), patch.object(native.os, 'killpg') as kill:
                with self.assertRaises(KeyboardInterrupt):
                    native.start(run, [], cap)
                kill.assert_called_once_with(123, native.signal.SIGTERM)
            self.assertEqual(json.loads((run / 'ledger.json').read_text())['state'], 'failed')

    def test_missing_launch_identity_remains_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            ledger = {'processes': []}
            child = Mock(pid=123, wait=Mock(side_effect=native.subprocess.TimeoutExpired('local', 5)))
            with patch.object(native.subprocess, 'Popen', return_value=child), patch.object(native, 'ticks', return_value=None), patch.object(native.signal, 'signal'), patch.object(native.os, 'killpg') as group, patch.object(native.os, 'kill') as single, patch.object(native, 'members') as discovery:
                with self.assertRaisesRegex(RuntimeError, 'identity capture'):
                    native.launch(run, ledger, 'local', ['local'], {})
                native.stop(run, ledger)
                group.assert_not_called()
                single.assert_not_called()
                discovery.assert_not_called()
            child.wait.assert_called_once_with(timeout=5)
            saved = json.loads((run / 'ledger.json').read_text())
            self.assertIsNone(saved['processes'][0]['start_ticks'])
            self.assertFalse(saved['cleanup_complete'])
            self.assertEqual(saved['state'], 'cleanup-incomplete')

    def test_authentication_rejects_socket_and_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'data').mkdir()
            native.restrict_auth(run)
            text = (run / 'data/pg_hba.conf').read_text()
            self.assertIn('local all all reject', text)
            self.assertIn('host all postgres 127.0.0.1/32 reject', text)
            self.assertNotIn('trust', text)

    def test_diagnostics_redact_credentials_and_keep_error(self):
        import io
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'prepare.log'
            native.diagnostics(io.BytesIO(b'failure: hidden-value\n'), path,
                               {'OWNER_PASSWORD': 'hidden-value'})
            self.assertEqual(path.read_text(), 'failure: [redacted]\n')

    def test_leaderless_session_remains_owned(self):
        with patch.object(native, 'ticks', return_value=None), patch.object(native, 'members', return_value=[44]):
            self.assertTrue(native.owned({'pid': 42, 'start_ticks': '12'}))

    def test_forced_shutdown_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = {'processes': [{'pid': 42, 'start_ticks': '12'}]}
            with patch.object(native, 'owned', return_value=True), patch.object(native.os, 'killpg') as kill, patch.object(native.time, 'monotonic', side_effect=[0, 11, 12, 18]):
                native.stop(Path(directory), ledger)
            self.assertEqual(ledger['state'], 'cleanup-incomplete')
            self.assertFalse(ledger['cleanup_complete'])
            self.assertEqual(kill.call_count, 2)


class AdmissionTests(unittest.TestCase):
    def test_stop_after_admission_expiry_cleans_only_owned_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            survivor = {'pid': 42, 'start_ticks': '12'}
            foreign = {'pid': 43, 'start_ticks': '13'}
            native.save(run, {'schema_version': 1, 'state': 'ready',
                              'processes': [survivor, foreign]})
            argv = ['native-stack.py', 'stop', '--run-dir', directory]
            with patch.object(native.sys, 'argv', argv), \
                    patch.object(native, 'admission', side_effect=ValueError('expired admission')) as admission, \
                    patch.object(native, 'capability', side_effect=AssertionError) as capability, \
                    patch.object(native, 'ticks', side_effect=lambda pid: '12' if pid == 42 else '99'), \
                    patch.object(native, 'members', side_effect=[[42], [], [], [], []]), \
                    patch.object(native, 'signal_session') as terminate, \
                    patch.object(native.os, 'kill', side_effect=AssertionError), \
                    patch.object(native.os, 'killpg', side_effect=AssertionError):
                native.main()
            admission.assert_not_called()
            capability.assert_not_called()
            terminate.assert_called_once_with(survivor, native.signal.SIGTERM)
            saved = json.loads((run / 'ledger.json').read_text())
            self.assertEqual(saved['state'], 'stopped')
            self.assertTrue(saved['cleanup_complete'])

    def test_exact_installed_authorization_and_rejections(self):
        marker = {'schema_version': 1, 'state': 'closed', 'batch_id': 'bounded',
                  'expires_at': 200, 'pid': 42, 'start_ticks': '12',
                  'lock': '/tmp/batch.lock', 'lock_identity': '00:01:99'}
        contract = Mock()
        contract.stat.return_value = Mock(st_uid=0, st_mode=0o100600)
        metadata = Mock(st_dev=1, st_ino=99)
        row = '1: FLOCK ADVISORY WRITE 42 00:01:99 0 EOF\n'
        with patch.object(native, 'ADMISSION', contract), patch.object(native.Path, 'stat', return_value=metadata), patch.object(native.Path, 'read_text', return_value=row) as kernel, patch.object(native, 'ticks', return_value='12') as stamp, patch.object(native.time, 'time', return_value=100):
            contract.read_text.return_value = json.dumps(marker)
            native.admission({'batch_id': 'bounded'})
            for change in ({'state': 'open'}, {'batch_id': 'other'}, {'expires_at': 99}, {'lock_identity': '00:01:98'}, {'schema_version': 2}):
                contract.read_text.return_value = json.dumps(dict(marker, **change))
                with self.assertRaises(ValueError):
                    native.admission({'batch_id': 'bounded'})
            contract.read_text.return_value = json.dumps(marker)
            for lock_row in ('', row.replace('WRITE', 'READ'), row.replace('42 ', '43 ')):
                kernel.return_value = lock_row
                with self.assertRaises(ValueError):
                    native.admission({'batch_id': 'bounded'})
            kernel.return_value = row
            stamp.return_value = '13'
            with self.assertRaises(ValueError):
                native.admission({'batch_id': 'bounded'})
            contract.stat.side_effect = FileNotFoundError
            with self.assertRaises(FileNotFoundError):
                native.admission({'batch_id': 'bounded'})

    def test_signal_reaches_child_in_another_group(self):
        entry = {'pid': 42, 'start_ticks': '12'}
        with patch.object(native.os, 'killpg', side_effect=ProcessLookupError), patch.object(native, 'members', return_value=[44]), patch.object(native, 'ticks', return_value='15'), patch.object(native.os, 'kill') as kill:
            native.signal_session(entry, native.signal.SIGKILL)
        kill.assert_called_once_with(44, native.signal.SIGKILL)

    def test_admission_loss_during_supervision_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            native.save(run, {'state': 'ready'})
            with patch.object(native, 'admission', side_effect=ValueError), patch.object(native.time, 'sleep', side_effect=AssertionError):
                with self.assertRaises(ValueError):
                    native.supervise(run, {'processes': []}, {})

    def test_supervisor_waits_for_stop_control(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            native.save(run, {'state': 'stopped', 'cleanup_complete': True})
            with patch.object(native.fcntl, 'flock', side_effect=[BlockingIOError, None, None]), patch.object(native.time, 'sleep') as sleep, patch.object(native, 'admission', side_effect=AssertionError):
                native.supervise(run, {'processes': []}, {})
            sleep.assert_called_once_with(.1)

    def test_database_diagnostics_redact_development_passwords(self):
        text = 'failed password ' + 'local-identity-owner'
        self.assertEqual(native.redact(text, {}), 'failed password [redacted]')
