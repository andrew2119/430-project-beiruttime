"""Bounded command and collection contract checks."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[3]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = load('native-runtime-tests')
dispatch = load('test-services')


class DispatchTests(unittest.TestCase):
    def test_native_service_processes(self):
        with patch.object(dispatch, 'run') as run, patch.object(dispatch.subprocess, 'check_output') as config, \
                patch.dict('os.environ', {'TEST_RUNTIME_URL_IDENTITY': 'test-identity', 'TEST_RUNTIME_URL_ORDERS': 'test-orders'}):
            dispatch.main(['--backend', 'native', '--run-dir', '/tmp/test-run', 'identity', 'orders'])
        self.assertEqual(run.call_count, 2)
        self.assertEqual([call.args[2] for call in run.call_args_list], ['identity', 'orders'])
        config.assert_not_called()

    def test_native_failure_propagates(self):
        with patch.object(dispatch, 'run', side_effect=RuntimeError('test failure')) as run, \
                patch.dict('os.environ', {'TEST_RUNTIME_URL_ORDERS': 'test-orders'}):
            with self.assertRaises(RuntimeError):
                dispatch.main(['--backend', 'native', '--run-dir', '/tmp/test-run', 'orders', 'identity'])
        self.assertEqual(run.call_count, 1)

    def test_container_default_arguments(self):
        config = {'name': 'test', 'services': {
            'postgres': {'environment': {'POSTGRES_PASSWORD': 'test-password'}},
            'identity': {'build': {'dockerfile': 'test-file', 'args': {'SERVICE_PATH': 'services/identity'}},
                         'environment': {'BT_DATABASE_URL': 'test-runtime'}}}}
        with patch.object(dispatch.subprocess, 'check_output', side_effect=[json.dumps(config), 'postgres']), \
                patch.object(dispatch, 'run') as run:
            dispatch.main(['identity'])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[:5], ('docker', 'build', '--target', 'test', '-f'))
        self.assertEqual(run.call_args_list[1].kwargs['env']['TEST_RUNTIME_URL'], 'test-runtime')

    def test_collection_matches_each_original(self):
        for service in native.SERVICES:
            for lane in ('L00', 'L01', 'L11'):
                captured = []
                fake = Mock()
                fake.main.side_effect = lambda args: captured.extend(args) or 0
                with patch.dict('sys.modules', {'pytest': fake}), patch.dict('os.environ', {
                        'BT_SERVICE_NAME': service, 'BT_TEST_LANE': lane}), \
                        patch.object(Path, 'is_dir', return_value=False):
                    with self.assertRaises(SystemExit):
                        exec((ROOT / 'services' / service / 'runtime/run_tests.py').read_text(), {})
                    self.assertEqual(captured[2:-3], native.collection(service, lane))

    def test_service_lane_subtree(self):
        with patch.object(Path, 'is_dir', return_value=True):
            self.assertEqual(native.collection('orders', 'L08')[-1], '/lane-tests/L08/orders')

    def test_database_targets(self):
        env = {'TEST_DATABASE_ADMIN_URL': 'postgresql://postgres:test-password@localhost:5432/postgres',
               'TEST_RUNTIME_URL': 'postgresql://bt_test_abc:test-password@localhost:5432/bt_test_abc'}
        self.assertEqual(native.database_environment('orders', env)['BT_MODULES_PATH'], '/app/modules')
        for value in ('postgresql://postgres:test-password@localhost:5432/postgres',
                      'postgresql://owner:test-password@localhost:5432/bt_test_abc',
                      env['TEST_RUNTIME_URL'] + '?options=test'):
            with self.assertRaises(ValueError):
                native.database_environment('orders', {**env, 'TEST_RUNTIME_URL': value})
        with self.assertRaises(ValueError):
            native.database_environment('orders', {})

    def test_missing_layout_is_nonzero(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(native.subprocess, 'run') as run:
            self.assertEqual(native.main(['orders', '--run-dir', folder, '--require-all']), 2)
            run.assert_not_called()

    def test_layout_check_is_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'orders'
            target.mkdir()
            layout = target / 'layout.json'
            layout.write_text(json.dumps({'schema_version': 1, 'service': 'orders', 'read_only': True,
                                         'mappings': native.mappings('orders'), 'launcher': ['test-layout']}))
            before = layout.read_bytes()
            with patch.object(native.subprocess, 'run') as run:
                self.assertEqual(native.main(['orders', '--run-dir', folder, '--check-layout']), 0)
                run.assert_not_called()
            self.assertEqual(layout.read_bytes(), before)
            self.assertEqual(list(target.iterdir()), [layout])

    def test_launch_failure_and_missing_result(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'orders'
            target.mkdir()
            layout = target / 'layout.json'
            layout.write_text(json.dumps({'schema_version': 1, 'service': 'orders', 'read_only': True,
                                         'mappings': native.mappings('orders'), 'launcher': ['test-layout']}))
            with patch.object(native, 'database_environment', return_value={}), \
                    patch.object(native.subprocess, 'run', return_value=Mock(returncode=7)) as run:
                self.assertEqual(native.main(['orders', '--run-dir', folder]), 7)
                self.assertIn('--worker', run.call_args.args[0])
                self.assertEqual(run.call_args.kwargs['env']['BT_TEST_LANE'], 'L00')
            with patch.object(native, 'database_environment', return_value={}), \
                    patch.object(native.subprocess, 'run', return_value=Mock(returncode=0)):
                self.assertEqual(native.main(['orders', '--run-dir', folder]), 2)

    def test_worker_requires_namespace(self):
        options = Mock(service='orders')
        with patch.object(Path, 'samefile', return_value=False), patch.object(native.os, 'chdir') as change:
            with self.assertRaises(ValueError):
                native.worker(options)
            change.assert_not_called()

    def test_skips_and_opt_in_are_incomplete(self):
        results = native.RequiredResults()
        results.pytest_collection_finish(Mock(items=[1, 2]))
        results.pytest_runtest_logreport(Mock(skipped=True, nodeid='test-required'))
        results.pytest_deselected([Mock(nodeid='test-opt-in')])
        self.assertEqual(results.collected, 2)
        self.assertEqual(results.incomplete, ['test-required', 'test-opt-in'])


if __name__ == '__main__':
    unittest.main()
