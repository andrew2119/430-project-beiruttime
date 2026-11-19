"""Bounded layout checks; no service or provider execution."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('proof_paths', Path(__file__).with_name('paths.py'))
paths = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paths)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'tests/lanes/proof.py'
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def modules(self, root):
        for name, identifier in [('listings', 'L03.listings'), ('media', 'L03.media'), ('discovery', 'L04.discovery')]:
            folder = root / name
            folder.mkdir(parents=True)
            (folder / 'module.json').write_text(json.dumps({'id': identifier}))
        return root

    def fixtures(self, root):
        root.mkdir(parents=True)
        for name in ['watch', 'auction', 'provider-auction', 'provider-history']:
            (root / (name + '.v1.json')).write_text('{}')
        return root

    def repository(self):
        registration = self.root / 'contracts/registrations/L04.json'
        registration.parent.mkdir(parents=True)
        registration.write_text(json.dumps({'contracts': [{
            'namespace': 'catalog.discovery.v1', 'path': 'packages/contracts-catalog/discovery',
            'fixtures': ['packages/contracts-catalog/discovery/fixtures/' + name + '.v1.json'
                         for name in ['watch', 'auction', 'provider-auction', 'provider-history']],
        }]}))

    def test_repository_layout(self):
        self.repository()
        modules = self.modules(self.root / 'services/catalog/modules')
        fixtures = self.fixtures(self.root / 'packages/contracts-catalog/discovery/fixtures')
        self.assertEqual(paths.catalog_modules(self.source), modules)
        self.assertEqual(paths.discovery_modules(self.source), modules / 'discovery')
        self.assertEqual(paths.contract_fixtures(self.source), fixtures)

    def test_explicit_roots_and_discovery_scope(self):
        modules = self.modules(self.root / 'native/modules')
        fixtures = self.fixtures(self.root / 'native/bt_contracts/catalog/discovery/fixtures')
        os.environ['BT_MODULES_PATH'] = str(modules)
        os.environ['BT_NATIVE_CONTRACT_ROOT'] = str(self.root / 'native')
        self.assertEqual(paths.catalog_modules(self.source), modules)
        self.assertEqual(paths.contract_fixtures(self.source), fixtures)
        os.environ['BT_MODULES_PATH'] = str(modules / 'discovery')
        self.assertEqual(paths.discovery_modules(self.source), modules / 'discovery')
        self.assertEqual(paths.catalog_modules(self.source), modules)

    def test_container_layout_without_repository(self):
        modules = self.modules(self.root / 'container/modules')
        fixtures = self.fixtures(self.root / 'container/contracts')
        original = paths.Path

        def mapped(value):
            return {'/app/modules': modules,
                    '/opt/domain-contracts/bt_contracts/catalog/discovery/fixtures': fixtures}.get(str(value), original(value))

        with patch.dict(paths.catalog_modules.__globals__, {'Path': mapped}):
            self.assertEqual(paths.catalog_modules(self.source), modules)
            self.assertEqual(paths.discovery_modules(self.source), modules / 'discovery')
            self.assertEqual(paths.contract_fixtures(self.source), fixtures)

    def test_invalid_explicit_roots_do_not_fall_back(self):
        self.repository()
        self.modules(self.root / 'services/catalog/modules')
        self.fixtures(self.root / 'packages/contracts-catalog/discovery/fixtures')
        os.environ['BT_MODULES_PATH'] = str(self.root / 'missing')
        os.environ['BT_NATIVE_CONTRACT_ROOT'] = str(self.root / 'missing')
        with self.assertRaisesRegex(RuntimeError, 'modules unavailable'):
            paths.catalog_modules(self.source)
        with self.assertRaisesRegex(RuntimeError, 'fixtures unavailable'):
            paths.contract_fixtures(self.source)

    def test_wrong_module_identity_and_incomplete_contracts_fail(self):
        modules = self.modules(self.root / 'native/modules')
        (modules / 'media/module.json').write_text('{"id":"L04.discovery"}')
        os.environ['BT_MODULES_PATH'] = str(modules)
        with self.assertRaises(RuntimeError):
            paths.catalog_modules(self.source)
        fixtures = self.fixtures(self.root / 'native/bt_contracts/catalog/discovery/fixtures')
        (fixtures / 'provider-history.v1.json').unlink()
        os.environ['BT_NATIVE_CONTRACT_ROOT'] = str(self.root / 'native')
        with self.assertRaises(RuntimeError):
            paths.contract_fixtures(self.source)


class DiscoveryScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_fixture_passes_only_discovery_to_inventory(self):
        import ast
        import inspect
        from types import SimpleNamespace

        source = Path(__file__).resolve().parents[2] / 'lanes/L04/test_discovery.py'
        tree = ast.parse(source.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                        and node.name == 'database_access')
        function.decorator_list = []
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        selected = Path('/tmp/catalog-proof/modules/discovery')
        calls = []
        access = object()

        async def inventory(request, tmp_path):
            calls.append((request, tmp_path, os.environ['BT_MODULES_PATH']))
            try:
                yield access
            finally:
                calls.append('closed')

        def setenv(name, value):
            os.environ[name] = value

        namespace = {
            'discovery_modules': lambda: selected,
            'runtime_testing': SimpleNamespace(database_access=SimpleNamespace(__wrapped__=inventory)),
            'inspect': inspect,
        }
        exec(compile(module, str(source), 'exec'), namespace)
        with patch.dict(os.environ, {'BT_MODULES_PATH': '/tmp/catalog-proof/modules'}):
            generator = namespace['database_access'](SimpleNamespace(setenv=setenv), 'request', Path('/tmp'))
            self.assertIs(await anext(generator), access)
            await generator.aclose()
        self.assertEqual(calls, [('request', Path('/tmp'), str(selected)), 'closed'])


class BootstrapTests(unittest.TestCase):
    def test_original_lane_layout_loads_shared_roots_without_dependencies(self):
        import ast
        import runpy
        import shutil

        lanes = Path(__file__).resolve().parents[2] / 'lanes'
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'lane-tests'
            for name in ['L03/catalog/test_listing_lifecycle.py', 'L04/test_discovery.py', 'L04/browser_fixture.py']:
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(lanes / name, destination)
            # Execute the exact bootstrap expressions, without importing runtime dependencies.
            for name in ['L03/catalog/test_listing_lifecycle.py', 'L04/test_discovery.py']:
                source = target / name
                tree = ast.parse(source.read_text())
                statement = next(node for node in tree.body if isinstance(node, ast.Assign)
                                 and any(isinstance(item, ast.Name) and item.id == '_paths' for item in node.targets))
                namespace = {'Path': Path, 'runpy': runpy, '__file__': str(source)}
                exec(compile(ast.Module(body=[statement], type_ignores=[]), str(source), 'exec'), namespace)
                self.assertTrue(callable(namespace['_paths']['catalog_modules']))
                self.assertTrue(callable(namespace['_paths']['contract_fixtures']))


if __name__ == '__main__':
    unittest.main()
