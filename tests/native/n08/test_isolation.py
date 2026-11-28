"""Bounded layout and capability checks using local doubles."""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    'native_isolation', Path(__file__).resolve().parents[3] / 'scripts/native-isolation.py')
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = ['tests/foundation', 'tests/lanes/L00', 'contracts',
                 'tests/lanes/L05/communications', 'tests/lanes/L05/auction']
        for service in native.SERVICES:
            paths += [f'services/{service}/runtime', f'services/{service}/modules']
        for path in paths:
            (self.root / path).mkdir(parents=True)

    def test_service_layouts_are_read_only_and_bounded(self):
        for service in native.SERVICES:
            manifest = native.layout(self.root, service)
            self.assertTrue(all(m['read_only'] for m in manifest['mounts']))
            self.assertEqual(manifest['network'], 'private_loopback')
            for mount in manifest['mounts']:
                relative = Path(mount['source']).relative_to(self.root).as_posix()
                if relative.startswith('services/'):
                    self.assertTrue(relative.startswith(f'services/{service}/'))
            self.assertEqual(manifest['contracts_target'], '/opt/domain-contracts')
            self.assertEqual({m['target'] for m in manifest['mounts']}, {
                '/app', '/app/modules', '/foundation-tests', '/lane-tests/L00',
                '/contracts'})

    def test_exception_is_explicit(self):
        ordinary = native.layout(self.root, 'communications', 'L05')
        self.assertNotIn('/app/auction-modules', [m['target'] for m in ordinary['mounts']])
        special = native.layout(self.root, 'communications', 'L05', 'l05-cross-runtime')
        self.assertIn('/app/auction-modules', [m['target'] for m in special['mounts']])
        runtime = next(m for m in special['mounts'] if m['target'] == '/app')
        self.assertEqual(runtime['source'],
                         str(self.root / 'services/auction/runtime'))
        with self.assertRaises(native.IsolationError):
            native.layout(self.root, 'auction', 'L05', 'l05-cross-runtime')

    def test_l03_original_workspace_resolution(self):
        module = self.root / 'services/communications/modules/seller-workspace'
        module.mkdir()
        (self.root / 'tests/lanes/L03/communications').mkdir(parents=True)
        manifest = native.layout(self.root, 'communications', 'L03')
        mapping = next(m for m in manifest['mounts']
                       if m['target'] == '/workspace-module')
        self.assertEqual(mapping['source'], str(module))
        self.assertIs(mapping['read_only'], True)
        self.assertTrue(all('/services/communications/' in m['source']
                            for m in manifest['mounts']
                            if '/services/' in m['source']))
        schema = json.loads((Path(__file__).resolve().parents[3] /
                             'scripts/native-isolation.schema.json').read_text())
        self.assertRegex(mapping['target'],
                         schema['properties']['mounts']['items']['properties']
                         ['target']['pattern'])

        fixture = Path(__file__).resolve().parents[2] / 'lanes/L03/communications/test_workspace.py'
        tree = ast.parse(fixture.read_text())
        workspace = next(node for node in tree.body
                         if isinstance(node, ast.AsyncFunctionDef)
                         and node.name == 'workspace')
        resolution = ast.Module(body=workspace.body[:3], type_ignores=[])
        selected = object()
        discover = Mock(return_value=[selected])

        def mapped_path(value):
            self.assertEqual(value, '/workspace-module')
            return Path(mapping['source'])

        scope = {'Path': mapped_path, 'discover': discover}
        with patch.object(native.subprocess, 'run', side_effect=AssertionError), \
                patch.object(Path, 'mkdir', side_effect=AssertionError), \
                patch.object(Path, 'symlink_to', side_effect=AssertionError):
            exec(compile(resolution, '<workspace-resolution>', 'exec'), scope)
        discover.assert_called_once_with(module)
        self.assertIs(scope['module'], selected)
        ordinary = native.layout(self.root, 'communications')
        self.assertNotIn('/workspace-module', [m['target'] for m in ordinary['mounts']])
        other = self.root / 'tests/lanes/L03/orders'
        other.mkdir()
        self.assertNotIn('/workspace-module', [m['target'] for m in
                         native.layout(self.root, 'orders', 'L03')['mounts']])
        module.rmdir()
        backend = Mock()
        with self.assertRaises(native.IsolationError):
            native.run_service(self.root, 'communications', lane='L03', backend=backend)
        backend.assert_not_called()

    def test_empty_baseline_and_missing_inputs(self):
        self.assertEqual(native.layout(self.root, 'catalog', 'L10')['empty_read_only'],
                         ['/lane-tests/L10'])
        with self.assertRaises(native.IsolationError):
            native.layout(self.root, 'catalog', 'L11')

    def test_missing_service_lane_never_exposes_siblings(self):
        backend = Mock()
        with self.assertRaises(native.IsolationError):
            native.run_service(self.root, 'orders', lane='L05', backend=backend)
        backend.assert_not_called()
        manifest = native.layout(self.root, 'communications', 'L05')
        lanes = [m['target'] for m in manifest['mounts']
                 if m['target'].startswith('/lane-tests/L05')]
        self.assertEqual(lanes, ['/lane-tests/L05/communications'])
        (self.root / 'tests/lanes/L05/communications').rmdir()
        with self.assertRaises(native.IsolationError):
            native.layout(self.root, 'communications', 'L05')

    def test_shared_lanes_are_explicit(self):
        for lane in ('L02', 'L04'):
            (self.root / 'tests/lanes' / lane).mkdir()
            manifest = native.layout(self.root, 'orders', lane)
            self.assertIn('/lane-tests/' + lane,
                          [m['target'] for m in manifest['mounts']])
        (self.root / 'tests/lanes/L11').mkdir()
        with self.assertRaises(native.IsolationError):
            native.layout(self.root, 'orders', 'L11')

    def test_staging_rechecks_signing_files(self):
        manifest = native.layout(self.root, 'orders')
        for suffix in ('.p12', '.pfx'):
            with self.subTest(suffix=suffix):
                secret = self.root / 'contracts' / ('private' + suffix)
                secret.touch()
                runner = Mock(side_effect=[Mock(returncode=0)] * 3 +
                              [Mock(returncode=1)])
                with self.assertRaises(native.IsolationError):
                    native.staging_check(self.root, manifest, runner)
                secret.unlink()

    def test_no_global_mutation(self):
        with patch.object(Path, 'mkdir', side_effect=AssertionError), \
                patch.object(Path, 'symlink_to', side_effect=AssertionError), \
                patch.object(native.subprocess, 'run', side_effect=AssertionError):
            native.layout(self.root, 'orders')

    def test_secret_and_link_exclusion(self):
        directory = self.root / 'contracts'
        for name in ('.env', '.env.local', 'private.key', 'private.pem',
                     'private.p12', 'private.pfx'):
            secret = directory / name
            secret.touch()
            with self.assertRaises(native.IsolationError):
                native.layout(self.root, 'orders')
            secret.unlink()
        (directory / 'linked').symlink_to(self.root / 'services')
        with self.assertRaises(native.IsolationError):
            native.layout(self.root, 'orders')

    def test_ignore_checks_are_not_image_proof(self):
        runner = Mock(side_effect=[Mock(returncode=0)] * 3 + [Mock(returncode=1)])
        result = native.staging_check(self.root, native.layout(self.root, 'orders'), runner)
        self.assertEqual(result['unsupported'], ['image_build_context', 'image_content'])
        self.assertEqual(runner.call_count, 4)
        runner.return_value = Mock(returncode=2)
        runner.side_effect = None
        with self.assertRaises(native.IsolationError):
            native.staging_check(self.root, native.layout(self.root, 'orders'), runner)

    def test_fail_closed_before_execution(self):
        backend = Mock(return_value={'schema_version': 1, 'capabilities': {}})
        with self.assertRaises(native.IsolationError):
            native.run_service(self.root, 'orders', backend=backend)
        self.assertEqual(backend.call_count, 1)
        self.assertEqual(backend.call_args.args[0]['operation'], 'check')

    def test_every_capability_is_required(self):
        for missing in native.REQUIRED:
            capabilities = dict.fromkeys(native.REQUIRED, True)
            capabilities[missing] = False
            with self.assertRaises(native.IsolationError):
                native.check_backend(Mock(return_value={
                    'schema_version': 1, 'capabilities': capabilities,
                    'published_contracts_read_only': True}))

    def test_schema_manifest_fields(self):
        schema = json.loads((Path(__file__).resolve().parents[3] /
                             'scripts/native-isolation.schema.json').read_text())
        manifest = native.layout(self.root, 'orders')
        self.assertEqual(set(schema['required']), set(manifest))
        self.assertEqual(set(schema['properties']), set(manifest))
        self.assertFalse(schema['additionalProperties'])
        for key, rule in schema['properties'].items():
            if 'const' in rule:
                self.assertEqual(manifest[key], rule['const'])

    def test_invalid_selection_and_parent_link(self):
        for service, lane in (('../orders', 'L00'), ('orders', 'L12')):
            with self.assertRaises(native.IsolationError):
                native.layout(self.root, service, lane)
        (self.root / 'alias').symlink_to(self.root / 'services', target_is_directory=True)
        with self.assertRaises(native.IsolationError):
            native.safe_input(self.root, 'alias/orders/runtime')

    def test_unconfirmed_execution_is_failure(self):
        for result in ({}, {'schema_version': 1, 'isolation_enforced': True,
                            'exit_code': 1}):
            backend = Mock(side_effect=[{
                'schema_version': 1,
                'capabilities': dict.fromkeys(native.REQUIRED, True),
                'published_contracts_read_only': True}, result])
            with patch.object(native, 'staging_check', return_value={}):
                with self.assertRaises(native.IsolationError):
                    native.run_service(self.root, 'orders', backend=backend)

    @staticmethod
    def completion():
        return {'proof_id': 'orders:L00:service', 'state': 'complete',
                'collected': 2, 'passed': 2, 'skipped': 0, 'failed': 0,
                'errors': 0, 'deferred': []}

    def test_l11_shared_inputs_are_explicit_and_read_only(self):
        directory = self.root / 'tests/lanes/L11'
        directory.mkdir()
        (directory / 'catalog').mkdir()
        for name in native.L11_SHARED:
            (directory / name).touch()
        manifest = native.layout(self.root, 'catalog', 'L11')
        mappings = {m['target']: m for m in manifest['mounts']}
        expected = {'/lane-tests/L11/' + name for name in native.L11_SHARED}
        expected.add('/lane-tests/L11/catalog')
        self.assertEqual({key for key in mappings if key.startswith('/lane-tests/L11')},
                         expected)
        self.assertTrue(all(mappings[key]['read_only'] for key in expected))
        self.assertFalse(any('services/service-operations' in m['source']
                             for m in manifest['mounts']))
        (directory / 'conftest.py').unlink()
        with self.assertRaises(native.IsolationError):
            native.layout(self.root, 'catalog', 'L11')

    def test_zero_exit_rejects_incomplete_proofs(self):
        variants = [None, {}, *[
            dict(self.completion(), **change) for change in (
                {'state': 'deferred'}, {'skipped': 1}, {'failed': 1},
                {'errors': 1}, {'collected': 0, 'passed': 0},
                {'passed': 1}, {'collected': True}, {'proof_id': 'other'},
                {'deferred': [{'proof_id': 'database', 'reason': 'unavailable'}]})]]
        for completion in variants:
            with self.subTest(completion=completion):
                backend = Mock(side_effect=[{
                    'schema_version': 1,
                    'capabilities': dict.fromkeys(native.REQUIRED, True),
                    'published_contracts_read_only': True}, {
                        'schema_version': 1, 'isolation_enforced': True,
                        'exit_code': 0, 'completion': completion}])
                with patch.object(native, 'staging_check', return_value={}):
                    with self.assertRaises(native.IsolationError):
                        native.run_service(self.root, 'orders', backend=backend)

    def test_dispatch_uses_clean_environment(self):
        backend = Mock(side_effect=[{
            'schema_version': 1, 'capabilities': dict.fromkeys(native.REQUIRED, True),
            'published_contracts_read_only': True}, {
                'schema_version': 1, 'isolation_enforced': True, 'exit_code': 0,
                'completion': self.completion()}])
        with patch.object(native, 'staging_check', return_value={}):
            native.run_service(self.root, 'orders', backend=backend)
        request = backend.call_args.args[0]
        self.assertEqual(request['completion_required'], {
            'proof_id': 'orders:L00:service', 'no_skips': True})
        self.assertEqual(request['argv'], ['python', '/app/run_tests.py'])
        self.assertEqual(set(request['environment']), {
            'BT_SERVICE_NAME', 'BT_TEST_LANE', 'PYTHONDONTWRITEBYTECODE', 'PYTHONPATH'})


if __name__ == '__main__':
    unittest.main()
