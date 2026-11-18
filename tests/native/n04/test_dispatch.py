"""Pure selection and provider-boundary regressions; no connected execution."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('native_lanes', ROOT / 'scripts/native-lanes.py')
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


def collection(selection):
    return {'schema_version': 1, 'request_fingerprint': selection['request_fingerprint'],
            'lifecycle_policy': selection['topology']['lifecycle_policy'], 'complete': True,
            'collected_nodeids': list(selection['expected_nodes'])}


def record(selection):
    return {'schema_version': 1, 'selection_id': selection['id'],
            'collection_fingerprint': dispatch.digest(collection(selection)),
            **{key: selection[key] for key in ('request_fingerprint', 'source_fingerprint',
                                             'dependency_fingerprint', 'topology')},
            'counts': {'collected': len(selection['expected_nodes']),
                       'passed': len(selection['expected_nodes']), 'failed': 0, 'errors': 0, 'skipped': 0},
            'collected_nodeids': selection['expected_nodes'],
            'nodes': [{'nodeid': node, 'outcome': 'passed'} for node in selection['expected_nodes']],
            'check_execution': {name: {'operation': operation, 'exit_code': 0,
                                     'phase': 'before-tests',
                                     **({'executed_argv': operation['argv']} if name == 'python-lint' else {'requirements': {path: [{'requirement': requirement,
                                                              'installed_version': next(iter(dispatch.Requirement(requirement).specifier)).version,
                                                              'satisfied': True}
                                                             for requirement in selection['requirement_inventory'][path]]
                                                      for path in operation['requirements']}}),
                                     'dependency_fingerprint': selection['dependency_fingerprint']}
                                for name, operation in selection['check_operations'].items()},
            'skips': [], 'checks': {name: 'passed' for name in selection['checks']}, 'result': 'passed'}


class DispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = dispatch.plan()
        cls.collections = {s['id']: collection(s) for s in cls.request['selections']}
        cls.selections = {s['id']: s for s in cls.request['selections']}

    def test_exact_inventory(self):
        expected = {
            'L00': ['identity', 'catalog', 'auction', 'pricing', 'orders', 'eligibility',
                    'trust', 'communications', 'service-operations'],
            'L01': ['identity', 'eligibility'], 'L02': ['identity'],
            'L03': ['catalog', 'communications'], 'L04': ['catalog'],
            'L05': ['auction', 'communications'], 'L06': ['auction', 'communications'],
            'L07': ['pricing', 'communications'], 'L08': ['orders', 'catalog'],
            'L09': ['trust', 'communications', 'service-operations'],
            'L10': ['catalog'], 'L11': ['catalog', 'service-operations']}
        ids = {lane + '-' + service for lane, services in expected.items() for service in services}
        ids.add('L09-directory-intake-integration')
        self.assertEqual(set(self.selections), ids)

    def test_special_topologies(self):
        notice = self.selections['L05-communications']['topology']
        self.assertEqual(notice['module_roots'], ['services/communications/modules/bid-notices'])
        self.assertEqual(notice['auction_module_root'], 'services/auction/modules')
        self.assertEqual(notice['database_domains'], ['auction', 'communications'])
        self.assertIn('tests/lanes/L05/auction', notice['import_roots'])
        self.assertEqual(notice['auction_factory'], 'services/auction/runtime/service_app')
        self.assertIn('tests/lanes/L05/communications/test_auction_delivery.py', notice['required_proofs'])
        for service, module in [('orders', 'allocation'), ('catalog', 'request-drafts')]:
            self.assertEqual(self.selections['L08-' + service]['topology']['module_roots'],
                             [f'services/{service}/modules/{module}'])
        options = self.selections['L10-catalog']['topology']
        self.assertEqual(options['core_baseline'], 'empty')
        self.assertEqual(len(options['module_roots']), 4)
        self.assertEqual(self.selections['L09-directory-intake-integration']['topology']['test_roots'],
                         ['tests/lanes/L09/integration/directory.py'])

    def test_plan_has_no_external_effects(self):
        with patch('subprocess.Popen', side_effect=AssertionError('process')), \
                patch('subprocess.run', side_effect=AssertionError('process')), \
                patch('socket.socket', side_effect=AssertionError('socket')):
            request = dispatch.plan()
        self.assertEqual(request, self.request)
        self.assertEqual(sum(c['id'] == 'web-build' for c in request['checks']), 1)
        self.assertTrue(all('dependency-pins' in s['checks'] for s in request['selections']))

    def test_missing_notice_tree_or_delivery_file_fails_planning(self):
        exists = Path.exists
        for missing in ('tests/lanes/L05/communications',
                        'tests/lanes/L05/communications/test_auction_delivery.py'):
            def present(path):
                return False if path == ROOT / missing else exists(path)

            with self.subTest(missing=missing), \
                    patch.object(Path, 'exists', present), \
                    patch('subprocess.Popen', side_effect=AssertionError('process')), \
                    patch('socket.socket', side_effect=AssertionError('socket')):
                with self.assertRaisesRegex(ValueError, 'Missing required test root'):
                    dispatch.plan()

    def test_empty_required_proof_fails_planning(self):
        read_text = Path.read_text

        def source(path, *args, **kwargs):
            if path == ROOT / 'tests/lanes/L05/communications/test_auction_delivery.py':
                return ''
            return read_text(path, *args, **kwargs)

        with patch.object(Path, 'read_text', source):
            with self.assertRaisesRegex(ValueError, 'Required proof has no covered test definitions'):
                dispatch.plan()

    def test_required_proof_cannot_disappear_from_both_inventories(self):
        selection = copy.deepcopy(self.selections['L05-communications'])
        proof = selection['topology']['required_proofs'][0]
        selection['expected_nodes'] = [node for node in selection['expected_nodes']
                                       if not node.startswith(proof + '::')]
        complete = collection(selection)
        changed = record(selection)
        with self.assertRaisesRegex(ValueError, 'Required proof omitted'):
            dispatch.validate_record(selection, changed, complete)

    def test_missing_test_file_fails_static_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'Missing required test root'):
                dispatch.expected_nodes(Path(temporary), ['test_missing.py'])

    def test_fabricated_incomplete_success_is_rejected(self):
        records = {key: record(s) for key, s in self.selections.items()}
        checks = {c['id']: 'passed' for c in self.request['checks']}
        dispatch.validate_all(self.request, records, checks, self.collections)
        for missing in ['L09-directory-intake-integration', 'L05-communications']:
            changed = copy.deepcopy(records)
            del changed[missing]
            with self.assertRaises(ValueError):
                dispatch.validate_all(self.request, changed, checks, self.collections)
        changed = copy.deepcopy(records)
        del changed['L10-catalog']['checks']['dependency-pins']
        with self.assertRaises(ValueError):
            dispatch.validate_all(self.request, changed, checks, self.collections)
        changed = copy.deepcopy(records)
        changed['L05-communications']['topology'] = {}
        with self.assertRaises(ValueError):
            dispatch.validate_all(self.request, changed, checks, self.collections)

    def test_skips_counts_and_stale_sources_fail(self):
        selection = self.selections['L01-identity']
        for mutation in [lambda r: r.update(source_fingerprint='stale'),
                         lambda r: r['counts'].update(collected=0),
                         lambda r: r['counts'].update(failed=1, passed=1),
                         lambda r: r.update(skips=[{'nodeid': 'lifecycle', 'reason': 'opt-in',
                                                   'required': True}],
                                            counts={'collected': 2, 'passed': 1, 'failed': 0,
                                                    'errors': 0, 'skipped': 1})]:
            changed = copy.deepcopy(record(selection))
            mutation(changed)
            with self.assertRaises(ValueError):
                dispatch.validate_record(selection, changed, collection(selection))

    def test_stub_exchange_dispatches_every_selection_sequentially(self):
        calls = []

        def stub(argv, check, timeout):
            self.assertEqual(timeout, dispatch.PROVIDER_TIMEOUT_SECONDS)
            self.assertTrue(check)
            payload = json.loads(Path(argv[3]).read_text())
            calls.append(payload)
            if payload.get('operation') == 'collect':
                response = collection(payload['selection'])
            elif 'selection' in payload:
                response = record(payload['selection'])
            elif 'id' not in payload:
                response = {'request_fingerprint': payload['request_fingerprint'],
                            'checks': {c['id']: 'passed' for c in payload['checks']}}
            else:
                response = {'schema_version': 1, 'read_only': True,
                            'request_fingerprint': payload['request_fingerprint']}
            Path(argv[5]).write_text(json.dumps(response))

        with tempfile.TemporaryDirectory() as temporary, \
                patch('socket.socket', side_effect=AssertionError('socket')), \
                patch('subprocess.Popen', side_effect=AssertionError('process')), \
                patch('subprocess.run', side_effect=AssertionError('process')):
            summary = dispatch.execute(self.request, Path(temporary) / 'run',
                                       Path('layout.py'), Path('collection.py'), runner=stub)
        self.assertEqual(summary['failures'], {})
        self.assertEqual(len(calls), 3 * len(self.selections) + 1)
        self.assertEqual(len(summary['records']), len(self.selections))

    def test_aggregate_success_cannot_hide_required_tests(self):
        for key in ('L05-communications', 'L09-directory-intake-integration', 'L10-catalog'):
            selection = self.selections[key]
            changed = record(selection)
            changed['nodes'] = [{'nodeid': 'unrelated::test_sample', 'outcome': 'passed'}]
            changed['counts'].update(collected=1, passed=1)
            with self.assertRaises(ValueError):
                dispatch.validate_record(selection, changed, collection(selection))
        for malformed in ([], None, {'counts': None}):
            with self.assertRaises(ValueError):
                dispatch.validate_record(self.selections['L10-catalog'], malformed,
                                         self.collections['L10-catalog'])

    def test_parameter_case_cannot_disappear_after_collection(self):
        selection = self.selections['L09-directory-intake-integration']
        changed = record(selection)
        changed['collected_nodeids'] = [*selection['expected_nodes'],
                                       selection['expected_nodes'][0] + '[second]']
        with self.assertRaises(ValueError):
            dispatch.validate_record(selection, changed, collection(selection))

    def test_parameter_omitted_from_both_result_inventories_fails(self):
        selection = self.selections['L09-directory-intake-integration']
        complete = collection(selection)
        original = complete['collected_nodeids'][0]
        complete['collected_nodeids'][0:1] = [original + '[first]', original + '[second]']
        changed = record(selection)
        changed['collection_fingerprint'] = dispatch.digest(complete)
        changed['collected_nodeids'] = [original + '[first]', *selection['expected_nodes'][1:]]
        changed['nodes'] = [{'nodeid': node, 'outcome': 'passed'}
                            for node in changed['collected_nodeids']]
        with self.assertRaisesRegex(ValueError, 'Complete collection differs'):
            dispatch.validate_record(selection, changed, complete)
        changed['collected_nodeids'] = complete['collected_nodeids']
        changed['nodes'] = [{'nodeid': node, 'outcome': 'passed'}
                            for node in complete['collected_nodeids']]
        changed['counts'].update(collected=len(changed['nodes']), passed=len(changed['nodes']))
        dispatch.validate_record(selection, changed, complete)
        with self.assertRaises(ValueError):
            dispatch.validate_record(selection, changed)
        for field, value in [('complete', False), ('request_fingerprint', 'stale'),
                             ('lifecycle_policy', 'partial')]:
            invalid = {**complete, field: value}
            with self.assertRaises(ValueError):
                dispatch.validate_record(selection, changed, invalid)

    def test_requirement_coverage_and_versions_are_verified(self):
        selection = self.selections['L10-catalog']
        paths = selection['check_operations']['dependency-pins']['requirements']
        self.assertEqual(sum(map(len, selection['requirement_inventory'].values())), 9)
        for mutation in ('missing', 'invented', 'duplicate', 'outside', 'invalid'):
            changed = record(selection)
            entries = changed['check_execution']['dependency-pins']['requirements'][paths[0]]
            if mutation == 'missing':
                entries.pop()
            elif mutation == 'invented':
                entries[0]['requirement'] = 'fixture==1'
                entries[0]['installed_version'] = '1'
            elif mutation == 'duplicate':
                entries.append(copy.deepcopy(entries[0]))
            elif mutation == 'outside':
                entries[0]['installed_version'] = '0.0.0'
            else:
                entries[0]['installed_version'] = 'invalid'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                dispatch.validate_record(selection, changed, collection(selection))

    def test_lint_scopes_and_execution_are_required(self):
        for selection in self.selections.values():
            operation = selection['check_operations']['python-lint']
            self.assertEqual(operation['argv'], [
                'ruff', 'check', '--no-cache', '--config', operation['configuration'],
                *operation['targets']])
            self.assertTrue(operation['targets'])
            for target in operation['targets']:
                self.assertTrue((ROOT / target).exists(), target)
                changed = copy.deepcopy(record(selection))
                evidence = changed['check_execution']['python-lint']
                evidence['executed_argv'].remove(target)
                with self.subTest(selection=selection['id'], target=target), self.assertRaises(ValueError):
                    dispatch.validate_record(selection, changed, collection(selection))
            changed = copy.deepcopy(record(selection))
            del changed['check_execution']['python-lint']
            with self.assertRaises(ValueError):
                dispatch.validate_record(selection, changed, collection(selection))
        auction = self.selections['L05-auction']['check_operations']['python-lint']
        self.assertIn('services/auction/runtime/service_app', auction['targets'])
        self.assertIn('packages/contracts-auction/core/models.py', auction['targets'])
        options = self.selections['L10-catalog']['check_operations']['python-lint']
        self.assertEqual(options['targets'], [
            *self.selections['L10-catalog']['topology']['module_roots'],
            'packages/contracts-catalog/options', 'tests/lanes/L10'])

    def test_dependency_operation_requires_execution_evidence(self):
        selection = self.selections['L10-catalog']
        operation = selection['check_operations']['dependency-pins']
        self.assertEqual(operation['operation'], 'native-dependency-pins-v1')
        self.assertEqual(operation['requirements'], [
            'services/_template/runtime/requirements.txt',
            'services/_template/runtime/requirements-dev.txt'])
        for field, value in [('check_execution', {}), ('check_execution', {
                'dependency-pins': {'exit_code': 0}})]:
            changed = record(selection)
            changed[field] = value
            with self.assertRaises(ValueError):
                dispatch.validate_record(selection, changed, collection(selection))

    def test_timeout_cleans_partial_result_and_writes_failure(self):
        def stalled(argv, **kwargs):
            Path(argv[5]).write_text('{}')
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'run'
            summary = dispatch.execute(self.request, directory, Path('layout.py'),
                                       Path('collection.py'), runner=stalled)
            self.assertEqual(summary['result'], 'failed')
            self.assertEqual(summary['records'], {})
            self.assertIn('coverage', summary['failures'])
            self.assertEqual(summary, json.loads((directory / 'summary.json').read_text()))
            self.assertEqual(list(directory.glob('*-result.json')), [])

    def test_provider_timeout_and_cancellation_reap_group(self):
        for error in (subprocess.TimeoutExpired('provider', 1), KeyboardInterrupt()):
            with patch.object(dispatch.subprocess, 'Popen') as launch, \
                    patch.object(dispatch.os, 'killpg') as kill:
                process = launch.return_value
                process.pid = 123
                process.wait.side_effect = [error, 0, 0]
                with self.assertRaises(type(error)):
                    dispatch.run_provider(['provider'], check=True, timeout=1)
                self.assertEqual(kill.call_args_list, [
                    unittest.mock.call(123, dispatch.signal.SIGTERM),
                    unittest.mock.call(123, dispatch.signal.SIGKILL)])
                self.assertEqual(process.wait.call_args_list[-1].kwargs,
                                 {'timeout': dispatch.CLEANUP_TIMEOUT_SECONDS})

    def test_termination_reaps_group_removes_partial_and_restores_handler(self):
        for during_launch, cleanup_error in ((False, None), (False, ProcessLookupError()),
                                             (True, None)):
            handlers = {dispatch.signal.SIGTERM: object()}
            previous = handlers[dispatch.signal.SIGTERM]

            def install(signum, handler):
                handlers[signum] = handler

            def terminate_during_wait(*args, **kwargs):
                target.write_text('{}')
                handlers[dispatch.signal.SIGTERM](dispatch.signal.SIGTERM, None)

            delivered = False

            def mask(how, signals):
                nonlocal delivered
                if how == dispatch.signal.SIG_BLOCK:
                    self.assertEqual(signals, {dispatch.signal.SIGTERM})
                    return set()
                self.assertEqual(signals, set())
                if during_launch and not delivered:
                    delivered = True
                    terminate_during_wait()

            with tempfile.TemporaryDirectory() as temporary, \
                    patch.object(dispatch.signal, 'pthread_sigmask', side_effect=mask), \
                    patch.object(dispatch.signal, 'getsignal', side_effect=handlers.get), \
                    patch.object(dispatch.signal, 'signal', side_effect=install), \
                    patch.object(dispatch.subprocess, 'Popen') as launch, \
                    patch.object(dispatch.os, 'killpg', side_effect=cleanup_error) as kill, \
                    patch('socket.socket', side_effect=AssertionError('socket')):
                directory = Path(temporary)
                target = directory / 'sample-result.json'
                process = launch.return_value
                process.pid = 123
                waits = iter((lambda **kwargs: 0, lambda **kwargs: 0) if during_launch else
                             (terminate_during_wait, lambda **kwargs: 0, lambda **kwargs: 0))
                process.wait.side_effect = lambda **kwargs: next(waits)(**kwargs)
                with self.assertRaises(SystemExit) as caught:
                    dispatch.exchange(Path('provider.py'), {}, directory, 'sample',
                                      dispatch.run_provider)
                self.assertEqual(caught.exception.code, 128 + dispatch.signal.SIGTERM)
                launch.assert_called_once()
                self.assertTrue(launch.call_args.kwargs['start_new_session'])
                self.assertEqual(kill.call_args_list, [
                    unittest.mock.call(123, dispatch.signal.SIGTERM),
                    unittest.mock.call(123, dispatch.signal.SIGKILL)])
                self.assertEqual(process.wait.call_args_list[-1].kwargs,
                                 {'timeout': dispatch.CLEANUP_TIMEOUT_SECONDS})
                self.assertFalse(target.exists())
                self.assertIs(handlers[dispatch.signal.SIGTERM], previous)

    def test_missing_provider_never_passes(self):
        def unavailable(*args, **kwargs):
            raise FileNotFoundError('unavailable')
        with tempfile.TemporaryDirectory() as temporary:
            summary = dispatch.execute(self.request, Path(temporary) / 'run', Path('layout.py'),
                                       Path('collection.py'), runner=unavailable)
        self.assertEqual(summary['result'], 'failed')
        self.assertIn('coverage', summary['failures'])
        self.assertEqual(len(summary['failures']), len(self.selections) + 2)


if __name__ == '__main__':
    unittest.main()
