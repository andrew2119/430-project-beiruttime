import ast
from contextlib import ExitStack
import io
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import native_proof as proof


class NativeProofTests(unittest.TestCase):
    def test_original_origin_inventory(self):
        tree = ast.parse((proof.ROOT / 'infra/foundation/origin-smoke.py').read_text())
        assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'cases' for t in node.targets))
        edge_assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                               and any(isinstance(t, ast.Name) and t.id == 'edge' for t in node.targets))
        authority = ast.literal_eval(edge_assignment.value)['X-Forwarded-Host']
        for trusted in [False, True]:
            original = eval(compile(ast.Expression(assignment.value), '<inventory>', 'eval'),
                            {'public': 'http://localhost:3000', 'trusted': trusted,
                             'edge': ast.literal_eval(edge_assignment.value)})
            native = [(case['headers'], case['status']) for case in proof.plan('origin')['cases']
                      if case['trusted'] == trusted]
            self.assertEqual(len(original), len(native))
            for (old, status), (new, expected) in zip(original, native):
                self.assertEqual(status, expected)
                self.assertEqual(set(old), set(new))
                for key in old:
                    self.assertEqual(old[key].replace(authority, 'edge.test'), new[key])

    def test_plan_has_complete_nested_inventory(self):
        result = proof.plan('proxy')
        tree = ast.parse((proof.ROOT / 'infra/foundation/proxy-smoke.py').read_text())
        routes_node = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == 'routes' for t in node.targets))
        routes = eval(compile(ast.Expression(routes_node), '<inventory>', 'eval'),
                      {'args': type('Options', (), {'overlay': False})()})
        loops = [ast.literal_eval(node.iter) for node in ast.walk(tree)
                 if isinstance(node, (ast.For, ast.comprehension))
                 and isinstance(node.target, ast.Name) and node.target.id in {'locale', 'method'}
                 and isinstance(node.iter, ast.List)]
        self.assertIn(['en', 'ar'], loops)
        self.assertIn(['GET', 'HEAD'], loops)
        expected = {(route, locale, method, probe, query)
                    for route in routes for locale in ['en', 'ar']
                    for method in ['GET', 'HEAD'] for probe in ['public', 'loopback']
                    for query in ['', 'view=open']}
        self.assertEqual(len(result['cases']), len(expected))
        self.assertEqual({(c['route'], c['locale'], c['method'], c['probe'], c['query'])
                          for c in result['cases']}, expected)
        for case in result['cases']:
            self.assertEqual(case['status'], 200)
            self.assertEqual(case['headers'], {} if not case['query'] else
                             {'Cookie': 'bt-locale=' + ('ar' if case['locale'] == 'en' else 'en')})
        self.assertEqual(result['redirects'], [
            {'route': route, 'locale': locale, 'statuses': [307, 308],
             'query': 'view=open', 'hops': 1}
            for route, locale in zip(routes, ['en', 'ar'])])
        browser = result['browser']
        self.assertEqual(browser['themes'], ['light', 'dark'])
        self.assertEqual(browser['widths'], [1440, 390])
        self.assertEqual(browser['state'], 'deferred')
        original = (proof.ROOT / 'tests/foundation/browser-nested-routes.js').read_text()
        mapping = {'path': 'path', 'search': 'query', 'locale': 'language',
                   'dir': 'direction', 'theme': 'theme', 'registered': 'registration',
                   'internalPath': 'internal-path', 'forwardedLocale': 'forwarded-locale',
                   'width': 'width', 'overflow': 'no-overflow'}
        self.assertEqual(set(browser['assertions']), set(mapping.values()))
        for name in mapping:
            self.assertIn('check.' + name, original)

    def test_proxy_assertions_and_negative_cases(self):
        public = 'http://localhost:3000'

        def reply(url, headers=None, method='GET'):
            path = proof.urlsplit(url).path
            if path in proof.ROUTES:
                locale = headers['Cookie'].split('=')[1]
                return 307, {'location': '/' + locale + path + '?view=open'}, ''
            locale = path.split('/')[1]
            route = '/' + '/'.join(path.split('/')[2:])
            return 200, {}, (f'lang="{locale}" data-locale="{locale}" '
                             f'data-path="{route}" data-registered="true"')

        with patch.object(proof, 'response', side_effect=reply) as probe:
            proof.verify_proxy(public, 'http://127.0.0.1:3000')
            self.assertEqual(probe.call_count, 40)
            plain = [call for call in probe.call_args_list if call.args[1:] and call.args[1] is None]
            self.assertEqual(len(plain), 16)
        for failure in ['language', 'registration', 'location', 'query', 'authority', 'hop', 'plain-get', 'plain-head']:
            def broken(url, headers=None, method='GET'):
                status, fields, body = reply(url, headers, method)
                if failure == 'language':
                    body = body.replace('lang=', 'other=')
                elif failure == 'registration':
                    body = body.replace('true', 'false')
                elif failure == 'location' and status == 200:
                    fields = {'location': '/en'}
                elif failure == 'query' and status == 307:
                    fields['location'] = fields['location'].replace('view=open', 'view=closed')
                elif failure == 'authority' and status == 307:
                    fields['location'] = 'https://foreign.test' + fields['location']
                elif failure == 'hop' and status == 200 and headers and headers['Cookie'].endswith(proof.urlsplit(url).path.split('/')[1]):
                    status = 307
                elif failure == 'plain-' + method.lower() and headers is None:
                    status = 403
                return status, fields, body
            with self.subTest(failure=failure), patch.object(proof, 'response', side_effect=broken), self.assertRaises(AssertionError):
                proof.verify_proxy(public, 'http://127.0.0.1:3000')

    def test_plan_is_side_effect_free(self):
        for kind in ['origin', 'proxy']:
            with patch('sys.argv', ['proof', '--plan']), patch('sys.stdout', new_callable=io.StringIO) as output, patch.object(proof, 'prepare') as prepare, patch.object(proof.subprocess, 'Popen') as process, patch.object(proof, 'response') as response:
                with patch.object(proof.socket, 'socket') as socket, patch.object(proof.subprocess, 'run') as run:
                    proof.main(kind)
                    socket.assert_not_called()
                    run.assert_not_called()
                self.assertEqual(json.loads(output.getvalue())['schema_version'], 1)
                prepare.assert_not_called()
                process.assert_not_called()
                response.assert_not_called()

    def test_origin_assertions_reject_wrong_outcomes(self):
        public = 'http://localhost:3000'
        for trusted in [False, True]:
            replies = [(status, {}, json.dumps(
                {'proof': 'synthetic-origin-transport', 'origin': headers['Origin']}
                if status == 200 else {'error': {'code': 'invalid_origin'}}))
                for headers, status in proof.origin_cases(public, trusted)]
            with patch.object(proof, 'response', side_effect=replies) as response:
                proof.verify_origin(public, trusted)
                self.assertEqual(response.call_count, 9)
            replies[2] = (200, {}, '{}')
            with patch.object(proof, 'response', side_effect=replies), self.assertRaises(AssertionError):
                proof.verify_origin(public, trusted)

    def test_process_cleanup_on_failure(self):
        process = Mock()
        with patch.object(proof.subprocess, 'Popen', return_value=process):
            with self.assertRaises(RuntimeError):
                with ExitStack() as stack:
                    proof.start(stack, ['node'], Path('.'), {})
                    raise RuntimeError('probe failed')
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)

    def test_build_group_cleanup(self):
        for outcome in [0, 1, proof.subprocess.TimeoutExpired(['build'], 900), KeyboardInterrupt()]:
            with self.subTest(outcome=outcome):
                process = Mock(pid=1234)
                process.wait.side_effect = [outcome, 0, 0]
                with patch.object(proof.subprocess, 'Popen', return_value=process) as spawn, patch.object(proof.os, 'killpg') as kill:
                    if outcome == 0:
                        proof.build(['build'], Path('.'))
                    else:
                        expected = type(outcome) if isinstance(outcome, BaseException) else proof.subprocess.CalledProcessError
                        with self.assertRaises(expected):
                            proof.build(['build'], Path('.'))
                    spawn.assert_called_once_with(['build'], cwd=Path('.'), start_new_session=True)
                    self.assertEqual(process.wait.call_args_list[0].kwargs, {'timeout': 900})
                    self.assertEqual(kill.call_args_list, [
                        unittest.mock.call(1234, proof.signal.SIGTERM),
                        unittest.mock.call(1234, proof.signal.SIGKILL)])

    def test_build_cleanup_escalates_after_grace_period(self):
        process = Mock(pid=1234)
        process.wait.side_effect = [proof.subprocess.TimeoutExpired(['build'], 900),
                                    proof.subprocess.TimeoutExpired(['build'], 5), 0]
        with patch.object(proof.subprocess, 'Popen', return_value=process), patch.object(proof.os, 'killpg') as kill:
            with self.assertRaises(proof.subprocess.TimeoutExpired):
                proof.build(['build'], Path('.'))
        self.assertEqual(kill.call_args_list[-1], unittest.mock.call(1234, proof.signal.SIGKILL))
        self.assertEqual(process.wait.call_count, 3)

    def test_build_already_exited_group(self):
        process = Mock(pid=1234)
        process.wait.return_value = 0
        with patch.object(proof.subprocess, 'Popen', return_value=process), patch.object(proof.os, 'killpg', side_effect=ProcessLookupError):
            proof.build(['build'], Path('.'))

    def test_overlay_is_confined_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'input'
            root.mkdir()
            (root / 'web/registrations').mkdir(parents=True)
            (root / 'web/registrations/L00.ts').write_text('original')
            fixtures = root / 'tests/foundation/fixtures/web'
            fixtures.mkdir(parents=True)
            (fixtures / 'gateway-registration.ts').write_text('transport')
            run = Path(directory) / 'run'
            source = proof.prepare(root, run, 'origin')
            self.assertEqual((root / 'web/registrations/L00.ts').read_text(), 'original')
            self.assertEqual((source / 'web/registrations/L00.ts').read_text(), 'transport')
            self.assertTrue((run / 'origin/source-fingerprints.json').is_file())
            with self.assertRaises(FileExistsError):
                proof.prepare(root, run, 'origin')
            with self.assertRaises(ValueError):
                proof.prepare(root, root / 'run', 'origin')

    def test_dependency_links_resolve_inside_fingerprinted_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'input'
            registration = root / 'web/registrations/L00.ts'
            registration.parent.mkdir(parents=True)
            registration.write_text('original')
            fixtures = root / 'tests/foundation/fixtures/web'
            fixtures.mkdir(parents=True)
            (fixtures / 'gateway-registration.ts').write_text('transport')
            package = root / 'packages/shared'
            package.mkdir(parents=True)
            (package / 'index.js').write_text('copied workspace bytes')
            store = root / 'node_modules/.store/external'
            store.mkdir(parents=True)
            (store / 'index.js').write_text('installed dependency bytes')
            modules = root / 'web/node_modules'
            modules.mkdir(parents=True)
            (modules / 'shared').symlink_to('../../packages/shared')
            (modules / 'external').symlink_to('../../node_modules/.store/external')
            nested = store / 'node_modules'
            nested.mkdir()
            (nested / 'shared').symlink_to('../../../../packages/shared')
            outside = Path(directory) / 'installed'
            outside.mkdir()
            (outside / 'index.js').write_text('external bytes')
            (modules / 'outside').symlink_to(outside)
            before = (modules / 'shared').readlink()
            with patch.object(proof.subprocess, 'Popen') as process, patch.object(proof.socket, 'socket') as socket:
                source = proof.prepare(root, Path(directory) / 'run', 'origin')
                process.assert_not_called()
                socket.assert_not_called()
            copied = source / 'web/node_modules'
            self.assertFalse(copied.is_symlink())
            self.assertEqual((copied / 'shared').resolve(), source / 'packages/shared')
            self.assertEqual((copied / 'external').resolve(), source / 'node_modules/.store/external')
            self.assertEqual((copied / 'external/node_modules/shared').resolve(), source / 'packages/shared')
            self.assertEqual((copied / 'outside').resolve(), outside)
            fingerprints = json.loads((source.parent / 'source-fingerprints.json').read_text())
            content = (copied / 'shared/index.js').read_bytes()
            self.assertEqual(fingerprints['packages/shared/index.js'], proof.hashlib.sha256(content).hexdigest())
            (package / 'index.js').write_text('changed input bytes')
            (store / 'index.js').write_text('changed dependency bytes')
            self.assertEqual((copied / 'shared/index.js').read_bytes(), content)
            self.assertEqual((copied / 'external/index.js').read_text(), 'installed dependency bytes')
            self.assertEqual((modules / 'shared').readlink(), before)

    def test_proxy_overlay_replaces_existing_grouped_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'input'
            registration = root / 'web/registrations/L00.ts'
            registration.parent.mkdir(parents=True)
            registration.write_text('original registration')
            fixtures = root / 'tests/foundation/fixtures/web'
            fixtures.mkdir(parents=True)
            (fixtures / 'nested-registration.ts').write_text('nested registration')
            (fixtures / 'nested-page.tsx').write_text('nested fixture')
            existing = [
                'web/app/(operations)/operations/moderation/page.tsx',
                'web/app/(account)/(private)/seller/dashboard/page.jsx',
                'web/app/seller/dashboard/page.js',
            ]
            retained = [
                'web/app/(account)/seller/dashboard/layout.tsx',
                'web/app/(account)/seller/other/page.tsx',
                'web/app/(account)/seller/dashboard/details/page.tsx',
            ]
            for name in existing + retained:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            source = proof.prepare(root, Path(directory) / 'run', 'proxy')
            fingerprints = json.loads((source.parent / 'source-fingerprints.json').read_text())
            for name in existing:
                self.assertEqual((root / name).read_text(), name)
                self.assertFalse((source / name).exists())
                self.assertEqual(fingerprints[name], proof.hashlib.sha256(name.encode()).hexdigest())
            for name in retained:
                self.assertEqual((source / name).read_text(), name)
            for route in proof.ROUTES:
                page = source / 'web/app/(foundation-proxy-proof)' / route.lstrip('/') / 'page.tsx'
                self.assertEqual(page.read_text(), 'nested fixture')
            self.assertEqual(registration.read_text(), 'original registration')

    def test_proxy_overlay_current_registration_inventory(self):
        registrations = proof.ROOT / 'web/registrations'
        inventory = sorted(registrations.glob('L[0-9][0-9].ts'))
        self.assertTrue(inventory)
        before = {entry.name: entry.read_bytes() for entry in inventory}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'input'
            destination = root / 'web/registrations'
            destination.mkdir(parents=True)
            for name, content in before.items():
                (destination / name).write_bytes(content)
            fixtures = root / 'tests/foundation/fixtures/web'
            fixtures.mkdir(parents=True)
            for name in ['nested-registration.ts', 'nested-page.tsx']:
                (fixtures / name).write_bytes(
                    (proof.ROOT / 'tests/foundation/fixtures/web' / name).read_bytes())
            source = proof.prepare(root, Path(directory) / 'run', 'proxy')
            copied = source / 'web/registrations'
            def paths(text):
                start = re.search(r"\broutes\s*:\s*\[", text).end()
                depth = 1
                end = start
                while depth:
                    if text[end] == '[':
                        depth += 1
                    elif text[end] == ']':
                        depth -= 1
                    end += 1
                return re.findall(r"\bpath\s*:\s*['\"]([^'\"]+)['\"]", text[start:end])
            resulting = paths((copied / 'foundation-original.ts').read_text())
            resulting += paths((copied / 'L00.ts').read_text())
            removed = []
            for name, content in before.items():
                if name == 'L00.ts':
                    continue
                original = copied / ('foundation-original-' + name)
                self.assertEqual(original.read_bytes(), content)
                # Match the whole wrapper: only the exact fixture paths are filtered.
                self.assertEqual((copied / name).read_text(),
                    f"import original from './{original.stem}';\n"
                    "export default { ...original, routes: original.routes.filter(\n"
                    f"  route => !{json.dumps(proof.ROUTES)}.includes(route.path)\n"
                    ") };\n")
                for route in paths(content.decode()):
                    if route in proof.ROUTES:
                        removed.append(route)
                    else:
                        resulting.append(route)
            self.assertCountEqual(removed, proof.ROUTES)
            self.assertEqual(len(resulting), len(set(resulting)))
            for route in proof.ROUTES:
                self.assertEqual(resulting.count(route), 1)
            for name, content in before.items():
                self.assertEqual((destination / name).read_bytes(), content)
                self.assertEqual((registrations / name).read_bytes(), content)

    def test_missing_browser_fails_before_copy(self):
        with patch('sys.argv', ['proof', '--browser']), patch.object(proof, 'prepare') as prepare, patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as result:
                proof.main('proxy')
            self.assertNotEqual(result.exception.code, 0)
            prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
