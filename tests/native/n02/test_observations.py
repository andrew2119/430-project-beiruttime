"""Measured inventories and private launcher exchange."""
import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from test_dispatch import native, service_layout


@pytest.fixture
def request_data(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "test_sample", raising=False)
    contract = native.lane_contract()
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'pytest.ini').write_text('[pytest]\nasyncio_default_fixture_loop_scope = function\n')
    (source / 'test_sample.py').write_text(
        'import pytest\n@pytest.mark.parametrize("value", [1, 2])\n'
        'def test_sample(value):\n    assert value > 0\n')
    selection = {'id': 'L00-identity', 'service': 'identity', 'lane': 'L00',
                 'request_fingerprint': 'test-request', 'source_fingerprint': 'test-source',
                 'dependency_fingerprint': 'test-dependencies', 'optional_skips': [],
                 'expected_nodes': ['test_sample.py::test_sample'], 'checks': [],
                 'check_operations': {}, 'topology': {
                     'test_command': ['python3', '-m', 'pytest', 'test_sample.py', '-q'],
                     'environment': {}, 'import_roots': [], 'required_proofs': ['test_sample.py'],
                     'lifecycle_policy': 'collect-and-run-all-opt-in-cases'}}
    selection['request_fingerprint'] = contract.digest(
        {key: value for key, value in selection.items() if key != 'request_fingerprint'})
    monkeypatch.setattr(native, 'ROOT', source)
    monkeypatch.setattr(contract, 'plan', lambda: {'selections': [selection]})
    monkeypatch.setattr(native, 'lane_contract', lambda: contract)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('BT_NATIVE_SANDBOX', '1')
    monkeypatch.setenv('TEST_DATABASE_ADMIN_URL',
                       'postgresql://maintenance:test-password@127.0.0.1:5432/postgres')
    monkeypatch.setenv('TEST_RUNTIME_URL',
                       'postgresql://bt_test_abc:test-password@127.0.0.1:5432/bt_test_abc')
    return {'schema_version': 1, 'operation': 'collect', 'selection': selection,
            'layout': {'schema_version': 1, 'read_only': True, 'source_root': str(source),
                       'request_fingerprint': selection['request_fingerprint'], 'service': 'identity',
                       'lane': 'L00', 'launcher': [native.LAUNCHER]}}


def execute_request(request):
    collected = native.observe(request)
    return {**request, 'operation': 'execute', 'collection': collected,
            'collection_fingerprint': native.lane_contract().digest(collected)}


def test_real_separate_precollection_and_parameter_execution(request_data):
    request = execute_request(request_data)
    assert request['collection']['collected_nodeids'] == [
        'test_sample.py::test_sample[1]', 'test_sample.py::test_sample[2]']
    output = native.observe(request)
    native.validate_observation(request, output)
    assert output['counts'] == {'collected': 2, 'passed': 2, 'failed': 0, 'errors': 0, 'skipped': 0}
    assert output['nodes'] == [{'nodeid': node, 'outcome': 'passed'}
                               for node in output['collected_nodeids']]


@pytest.mark.parametrize('body', [
    'import pytest\ndef test_sample():\n    pytest.skip("required lifecycle unavailable")\n',
    'def test_sample():\n    assert False\n',
    'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    raise ValueError("test setup")\n'
    'def test_sample():\n    pass\n',
    'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    yield\n'
    '    raise ValueError("test teardown")\ndef test_sample():\n    pass\n',
    'import pytest\n@pytest.mark.xfail\ndef test_sample():\n    assert False\n',
])
def test_unsuccessful_observations_fail(request_data, body):
    (native.ROOT / 'test_sample.py').write_text(body)
    request = execute_request(request_data)
    with pytest.raises(ValueError):
        native.observe(request)


def test_changed_inventory_and_stale_selection_fail(request_data):
    request = execute_request(request_data)
    request['collection']['collected_nodeids'].append('test_sample.py::test_sample[3]')
    request['collection_fingerprint'] = native.lane_contract().digest(request['collection'])
    with pytest.raises(ValueError):
        native.observe(request)
    with patch.object(native, 'lane_contract') as contract:
        contract.return_value.plan.return_value = {'selections': []}
        with pytest.raises(ValueError):
            native.validate_request(request_data)


def test_no_host_collection_and_private_exchange(request_data, tmp_path):
    request_file = tmp_path / 'request.json'
    result = tmp_path / 'result.json'
    native.write_private(request_file, request_data)
    options = argparse.Namespace(request=request_file, result=result, provider_worker=False)

    def launch(argv, **kwargs):
        assert argv[0] == native.LAUNCHER
        assert '--provider-worker' in argv
        assert 'TEST_RUNTIME_URL' not in kwargs['env']
        layout = json.loads(Path(argv[2]).read_text())
        assert layout['artifacts']['outputs'] == [str(result)]
        retained = Path(layout['artifacts']['inputs'][0]['source'])
        assert retained.stat().st_mode & 0o777 == 0o600
        native.write_private(result, {'schema_version': 1, 'operation': 'collect', 'complete': True,
                                     'request_fingerprint': request_data['selection']['request_fingerprint'],
                                     'lifecycle_policy': request_data['selection']['topology']['lifecycle_policy'],
                                     'collected_nodeids': ['test_sample.py::test_sample[1]']})
        return Mock(returncode=0)

    with patch.object(native.subprocess, 'run', side_effect=launch), patch.object(native, 'observe') as observe:
        assert native.observation_main(options) == 0
        observe.assert_not_called()
    assert result.stat().st_mode & 0o777 == 0o600
    before = result.read_bytes()
    assert native.observation_main(options) == 2
    assert result.read_bytes() == before


def test_failed_launcher_removes_result(request_data, tmp_path):
    request_file = tmp_path / 'request.json'
    result = tmp_path / 'result.json'
    native.write_private(request_file, request_data)
    options = argparse.Namespace(request=request_file, result=result, provider_worker=False)

    def failure(*args, **kwargs):
        native.write_private(result, {'complete': True})
        return Mock(returncode=2)

    with patch.object(native.subprocess, 'run', side_effect=failure):
        assert native.observation_main(options) == 2
    assert not result.exists()


def test_before_tests_measures_versions_and_exact_lint(tmp_path, monkeypatch):
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    (tmp_path / 'requirements.txt').write_text('pytest==8.3.0\n')
    selection = {'dependency_fingerprint': 'test-dependencies', 'check_operations': {
        'dependency-pins': {'requirements': ['requirements.txt']},
        'python-lint': {'argv': ['python3', '-m', 'ruff', 'check', 'test_sample.py']}}}
    with patch.object(native, 'version', return_value='8.3.0') as installed, \
            patch.object(native.subprocess, 'run', return_value=Mock(returncode=0)) as run:
        output = native.before_tests(selection)
        installed.assert_called_once_with('pytest')
        assert run.call_args.args[0] == selection['check_operations']['python-lint']['argv']
    assert output['dependency-pins']['requirements']['requirements.txt'] == [
        {'requirement': 'pytest==8.3.0', 'installed_version': '8.3.0', 'satisfied': True}]
    with patch.object(native, 'version', return_value='7.0.0'):
        with pytest.raises(ValueError):
            native.before_tests(selection)


def test_selected_mapping_has_no_siblings():
    result = native.mappings('orders', lane='L08')
    assert '/lane-tests' not in result
    assert '/lane-tests/L00' in result
    assert '/lane-tests/L08/orders' in result
    assert all('/L08/identity' not in value for value in result.values())


def test_namespace_and_layout_are_required(request_data):
    with patch.dict(os.environ, {'BT_NATIVE_SANDBOX': '0'}):
        with pytest.raises(ValueError):
            native.observe(request_data)
    request_data['layout']['launcher'] = ['sh', '-c']
    with pytest.raises(ValueError):
        native.validate_request(request_data)


def test_service_obtains_layout_without_host_database(tmp_path):
    options = ['identity', '--lane', 'L00', '--run-dir', str(tmp_path), '--require-all']

    def run(argv, **kwargs):
        assert 'TEST_RUNTIME_URL' not in kwargs['env']
        if '--worker' not in argv:
            request = json.loads(Path(argv[argv.index('--request') + 1]).read_text())
            assert request['operation'] == 'runtime-layout'
            assert request['service'] == 'identity'
            native.write_private(tmp_path / 'identity/layout.json', service_layout('identity', tmp_path))
        else:
            layout = json.loads(Path(argv[2]).read_text())
            assert layout['artifacts']['outputs'] == [str(tmp_path / 'identity/result.json')]
            native.write_private(tmp_path / 'identity/result.json', {
                'schema_version': 1, 'service': 'identity', 'lane': 'L00',
                'collection': native.collection('identity', 'L00'), 'collected': 1,
                'incomplete': [], 'exit_code': 0, 'state': 'complete'})
        return Mock(returncode=0)

    with patch.dict(os.environ, {}, clear=True), patch.object(native.subprocess, 'run', side_effect=run) as process:
        assert native.main(options) == 0
        assert process.call_count == 2


def test_timeout_is_nonzero_and_discards_output(request_data, tmp_path):
    request_file = tmp_path / 'request.json'
    result = tmp_path / 'result.json'
    native.write_private(request_file, request_data)
    options = argparse.Namespace(request=request_file, result=result, provider_worker=False)
    with patch.object(native.subprocess, 'run', side_effect=native.subprocess.TimeoutExpired('test', 600)):
        assert native.observation_main(options) == 124
    assert not result.exists()


@pytest.mark.parametrize('arguments', [['-k', 'missing'], []])
def test_deselection_and_empty_collection_fail(request_data, arguments):
    if arguments:
        selection = request_data['selection']
        selection['topology']['test_command'].extend(arguments)
        selection['request_fingerprint'] = native.lane_contract().digest(
            {key: value for key, value in selection.items() if key != 'request_fingerprint'})
        request_data['layout']['request_fingerprint'] = selection['request_fingerprint']
    else:
        (native.ROOT / 'test_sample.py').write_text('value = 1\n')
    with pytest.raises(ValueError):
        native.observe(request_data)


def test_result_validation_rejects_omitted_execution(request_data):
    request = execute_request(request_data)
    output = native.observe(request)
    output['nodes'].pop()
    with pytest.raises(ValueError):
        native.validate_observation(request, output)


def test_absent_service_subtree_never_exposes_other_services(tmp_path):
    lane = tmp_path / 'tests/lanes/L08'
    (lane / 'orders').mkdir(parents=True)
    result = native.mappings('identity', root=tmp_path, lane='L08')
    assert '/lane-tests/L08' not in result
    assert '/lane-tests/L08/identity' in result
    assert not any(value.endswith('/L08/orders') for value in result.values())


def test_shared_support_files_are_explicit():
    result = native.mappings('catalog', lane='L11')
    assert '/lane-tests/L11' not in result
    assert '/lane-tests/L11/catalog' in result
    assert '/lane-tests/L11/conftest.py' in result
    assert '/lane-tests/L11/service-operations' not in result


def test_worker_needs_only_selected_snapshot(request_data):
    contract = native.lane_contract()
    with patch.object(contract, 'plan', side_effect=AssertionError('Sibling sources are unavailable')):
        output = native.observe(request_data)
    assert output['complete'] is True


def test_layout_selection_binding_is_checked(tmp_path):
    directory = tmp_path / 'identity'
    directory.mkdir()
    layout = service_layout('identity', tmp_path)
    layout['lane'] = 'L01'
    native.write_private(directory / 'layout.json', layout)
    with patch.object(native.subprocess, 'run') as run:
        assert native.main(['identity', '--run-dir', str(tmp_path), '--check-layout']) == 2
        run.assert_not_called()


def test_delivery_mapping_retains_named_dependencies():
    result = native.mappings('communications', lane='L05')
    assert result['/app'] == str(native.ROOT / 'services/auction/runtime')
    assert result['/app/modules'] == str(native.ROOT / 'services/communications/modules')
    assert result['/app/auction-modules'] == str(native.ROOT / 'services/auction/modules')
    assert result['/lane-tests/L05/auction/test_admission.py'] == str(
        native.ROOT / 'tests/lanes/L05/auction/test_admission.py')
    assert '/lane-tests/L05/auction' not in result
    assert '/lane-tests/L05/communications' in result
    assert native.worker_import_roots('communications', 'L05') == [
        '/opt/domain-contracts', '/app', '/lane-tests/L05/auction']
    for service, lane in [('communications', 'L00'), ('auction', 'L05'), ('orders', 'L05')]:
        assert '/app/auction-modules' not in native.mappings(service, lane=lane)
        assert native.worker_import_roots(service, lane) == ['/app', '/opt/domain-contracts']


def test_delivery_layout_accepts_only_named_exceptions(tmp_path):
    directory = tmp_path / 'communications'
    directory.mkdir()
    layout = service_layout('communications', tmp_path, lane='L05')
    native.write_private(directory / 'layout.json', layout)
    assert native.check_layout('communications', tmp_path, lane='L05')[1] == [native.LAUNCHER]
    layout['mappings']['/lane-tests/L05/orders'] = str(native.ROOT / 'tests/lanes/L05/orders')
    native.write_private(directory / 'layout.json', layout)
    with pytest.raises(ValueError, match='contract mismatch'):
        native.check_layout('communications', tmp_path, lane='L05')


def test_delivery_worker_uses_import_order_and_retains_collection(tmp_path, monkeypatch):
    options = argparse.Namespace(service='communications', lane='L05', run_dir=tmp_path)
    (tmp_path / options.service).mkdir()
    monkeypatch.setenv('BT_NATIVE_SANDBOX', '1')
    monkeypatch.setattr(sys, 'path', list(sys.path))

    def run(arguments, plugins):
        assert sys.path[:3] == native.worker_import_roots(options.service, options.lane)
        assert arguments[2:6] == ['tests', 'modules', '/foundation-tests', '/lane-tests/L00']
        assert '/lane-tests/L05/communications' in arguments
        plugins[0].collected = 1
        return 0

    with patch.object(Path, 'samefile', return_value=True), patch.object(native.os, 'chdir'), \
            patch.object(pytest, 'main', side_effect=run):
        assert native.worker(options) == 0
