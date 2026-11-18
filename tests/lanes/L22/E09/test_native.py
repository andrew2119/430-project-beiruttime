import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from native import Execution, Unavailable


class ExecutionTests(unittest.TestCase):
    def execution(self, root):
        settings = root / 'native-v1.json'
        settings.write_text(json.dumps({'python': '/tmp/test-python/bin/python',
                                        'postgres_bin': '/tmp/test-postgres/bin'}))
        return Execution(root, settings)

    def test_external_provider_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.settings['environment'] = {'PAYMENT_URL': 'https://example.invalid'}
            with self.assertRaisesRegex(Unavailable, 'loopback-runtime-settings'):
                execution.environment('orders', Path(folder))

    def test_generated_settings_retained_and_paths_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            release = Path(folder) / 'test-release'
            env = execution.environment('orders', release)
            self.assertIn('@127.0.0.1:54329/', env['BT_DATABASE_URL'])
            self.assertEqual(env['BT_SERVICE_NAME'], 'orders')
            self.assertEqual(env['CATALOG_API_URL'], 'http://127.0.0.1:8102')
            self.assertEqual(env['BT_MODULES_PATH'], str(release / 'services/orders/modules'))
            self.assertIn(str(release / 'contracts'), env['PYTHONPATH'])

    def test_invalid_settings_refused_before_control_or_termination(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.settings['environment'] = {'PAYMENT_URL': 'https://example.invalid'}
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

    def test_reads_require_connected_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.settings['e09_reads'] = {name: {'url': 'http://127.0.0.1:8105/test'}
                                               for name in ('receipts', 'journal', 'custody')}
            response = Mock(status=200)
            response.read.return_value = b'{"synthetic": true, "seeded": false}'
            opener = Mock()
            opener.open.return_value.__enter__ = Mock(return_value=response)
            opener.open.return_value.__exit__ = Mock(return_value=False)
            with patch('native.urllib.request.build_opener', return_value=opener):
                with self.assertRaisesRegex(Unavailable, 'operation-provenance'):
                    execution.reads()
