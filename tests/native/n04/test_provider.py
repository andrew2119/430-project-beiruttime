"""Private provider exchanges with bounded observation doubles."""
import json
from pathlib import Path
import tempfile
from unittest import mock

import pytest

from test_dispatch import collection, dispatch, record


@pytest.fixture
def selection():
    return dispatch.plan()['selections'][0]


def request(selection, operation='collect'):
    result = {'schema_version': 1, 'operation': operation, 'selection': selection,
              'layout': {'schema_version': 1, 'read_only': True,
                         'request_fingerprint': selection['request_fingerprint']}}
    if operation == 'execute':
        result.update(collection=collection(selection),
                      collection_fingerprint=dispatch.digest(collection(selection)))
    return result


def observation(selection, operation):
    return {**collection(selection), **(record(selection) if operation == 'execute' else {}),
            'operation': operation, 'exit_code': 0}


@pytest.mark.parametrize('operation', ['collect', 'execute'])
def test_observed_envelope(selection, operation):
    observed = observation(selection, operation)

    def runner(argv, **kwargs):
        assert Path(argv[1]).name == 'native-runtime-tests.py'
        sent = json.loads(Path(argv[3]).read_text())
        assert sent == request(selection, operation)
        Path(argv[5]).write_text(json.dumps(observed))

    with tempfile.TemporaryDirectory() as temporary:
        result = dispatch.provide(request(selection, operation), Path(temporary), runner)
    if operation == 'collect':
        dispatch.validate_collection(selection, result)
    else:
        dispatch.validate_record(selection, result, collection(selection))


@pytest.mark.parametrize('field,value', [('complete', False), ('operation', 'other'),
                                        ('request_fingerprint', 'test-stale'),
                                        ('lifecycle_policy', 'optional')])
def test_incomplete_observation_rejected(selection, field, value):
    observed = observation(selection, 'collect')
    observed[field] = value
    with mock.patch.object(dispatch, 'exchange', return_value=observed):
        with pytest.raises(ValueError):
            dispatch.provide(request(selection), Path('/tmp'))


def test_execution_inventory_rejected(selection):
    observed = observation(selection, 'execute')
    observed['nodes'] = []
    with mock.patch.object(dispatch, 'exchange', return_value=observed):
        with pytest.raises(ValueError):
            dispatch.provide(request(selection, 'execute'), Path('/tmp'))


def test_stale_selection_never_invoked(selection):
    value = request(selection)
    value['selection']['topology']['test_command'] = ['false']
    with mock.patch.object(dispatch, 'exchange') as exchange:
        with pytest.raises(ValueError):
            dispatch.provide(value, Path('/tmp'))
        exchange.assert_not_called()


def test_shared_request_cannot_replace_commands():
    canonical = dispatch.plan()
    value = {'schema_version': 1, 'checks': [],
             'request_fingerprint': canonical['fingerprint']}
    with pytest.raises(ValueError):
        dispatch.shared_checks(value, canonical, Path('/tmp'), mock.Mock())


def test_configuration_validates_actual_manifest():
    assert dispatch.configuration(dispatch.ROOT)['exit_code'] == 0
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / 'scripts').mkdir()
        (root / 'scripts/native-services.json').write_text('{}')
        (root / 'scripts/native-stack.schema.json').write_text(
            (dispatch.ROOT / 'scripts/native-stack.schema.json').read_text())
        with pytest.raises(Exception):
            dispatch.configuration(root)


def test_private_output_and_fresh_execution_directory():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, target = root / 'request.json', root / 'result.json'
        source.write_text('{}')
        directories = []

        def provide(value, directory):
            directories.append(directory)
            assert directory.is_dir()
            return {'schema_version': 1}

        with mock.patch.object(dispatch, 'provide', side_effect=provide):
            assert dispatch.provider_files(source, target) == 0
            assert dispatch.provider_files(source, target) == 0
        assert directories[0] != directories[1]
        assert target.stat().st_mode & 0o777 == 0o600
        with mock.patch.object(dispatch, 'provide', side_effect=ValueError):
            assert dispatch.provider_files(source, target) == 2
        assert not target.exists()


def test_shared_checks_run_once_and_retain_bound_evidence():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        source, run = base / 'repository', base / 'run'
        source.mkdir()
        run.mkdir(mode=0o700)
        canonical = {'checks': [{'id': 'web-build', 'argv': ['test-build']},
                                {'id': 'configuration', 'argv': ['native-configuration-v1']}],
                     'fingerprint': 'test-current-source'}
        value = {'schema_version': 1, 'checks': canonical['checks'],
                 'request_fingerprint': canonical['fingerprint']}
        runner = mock.Mock()
        with mock.patch.object(dispatch, 'ROOT', source), \
                mock.patch.object(dispatch, 'plan', return_value=canonical), \
                mock.patch.object(dispatch, 'configuration', return_value={'exit_code': 0}) as config:
            response = dispatch.shared_checks(value, canonical, run, runner)
        assert response['checks'] == {'web-build': 'passed', 'configuration': 'passed'}
        runner.assert_called_once()
        assert runner.call_args.kwargs['cwd'] == run / 'source'
        assert runner.call_args.kwargs['env']['npm_config_offline'] == 'true'
        config.assert_called_once_with(run / 'source')
        evidence = json.loads((run / 'shared-execution.json').read_text())
        assert evidence['web-build']['request_fingerprint'] == canonical['fingerprint']
        assert (run / 'shared-execution.json').stat().st_mode & 0o777 == 0o600


def test_provider_cancellation_removes_result():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, target = root / 'request.json', root / 'result.json'
        source.write_text('{}')
        target.write_text('{}')
        with mock.patch.object(dispatch, 'provide', side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                dispatch.provider_files(source, target)
        assert not target.exists()


def test_shared_dependency_and_workspace_writes_stay_private(tmp_path):
    source, run = tmp_path / 'repository', tmp_path / 'run'
    modules = source / 'web' / 'node_modules'
    package = source / 'packages' / 'ui'
    external = tmp_path / 'dependencies'
    modules.mkdir(parents=True)
    package.mkdir(parents=True)
    external.mkdir()
    run.mkdir(mode=0o700)
    (package / 'index.js').write_text('export const value = 1;')
    (external / 'index.js').write_text('export const dependency = 1;')
    (modules / 'dependency').symlink_to(external, target_is_directory=True)
    (modules / 'workspace').symlink_to(package, target_is_directory=True)
    (modules / '.bin').mkdir()
    (modules / '.bin' / 'command').symlink_to('../dependency/index.js')
    canonical = {'checks': [{'id': 'web-unit', 'argv': ['test-unit']}],
                 'fingerprint': 'test-private-source'}
    value = {'schema_version': 1, 'checks': canonical['checks'],
             'request_fingerprint': canonical['fingerprint']}

    def runner(argv, **options):
        private = options['cwd'] / 'web' / 'node_modules'
        assert (private / 'workspace').resolve() == options['cwd'] / 'packages' / 'ui'
        assert (private / '.bin' / 'command').read_text() == (external / 'index.js').read_text()
        (private / '.vite').mkdir()
        (private / '.vite' / 'results.json').write_text('{}')
        (private / 'workspace' / 'index.js').write_text('private workspace output')
        (private / 'dependency' / 'index.js').write_text('private dependency output')
        for key in ('XDG_CACHE_HOME', 'npm_config_cache', 'TMPDIR'):
            assert Path(options['env'][key]).is_relative_to(run)
        assert Path(options['env']['TMPDIR']).is_dir()

    with mock.patch.object(dispatch, 'ROOT', source), \
            mock.patch.object(dispatch, 'plan', return_value=canonical):
        result = dispatch.shared_checks(value, canonical, run, runner)
    assert result['checks'] == {'web-unit': 'passed'}
    assert not (modules / '.vite').exists()
    assert (package / 'index.js').read_text() == 'export const value = 1;'
    assert (external / 'index.js').read_text() == 'export const dependency = 1;'


@pytest.mark.parametrize('directory_link', [False, True])
def test_shared_source_escape_rejected_before_execution(tmp_path, directory_link):
    source, run = tmp_path / 'repository', tmp_path / 'run'
    source.mkdir()
    run.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    sentinel = outside / 'value.txt'
    sentinel.write_text('original')
    (source / 'linked').symlink_to(outside if directory_link else sentinel,
                                 target_is_directory=directory_link)
    canonical = {'checks': [{'id': 'check', 'argv': ['test-command']}],
                 'fingerprint': 'test-source'}
    value = {'schema_version': 1, 'checks': canonical['checks'],
             'request_fingerprint': canonical['fingerprint']}
    runner = mock.Mock()
    with mock.patch.object(dispatch, 'ROOT', source):
        with pytest.raises(ValueError, match='Source link escapes'):
            dispatch.shared_checks(value, canonical, run, runner)
    runner.assert_not_called()
    assert sentinel.read_text() == 'original'


def test_internal_source_link_redirected(tmp_path):
    source, work = tmp_path / 'repository', tmp_path / 'private'
    source.mkdir()
    work.mkdir()
    (source / 'value.txt').write_text('original')
    (source / 'linked').symlink_to(source / 'value.txt')
    (work / 'value.txt').write_text('private')
    (work / 'linked').symlink_to(source / 'value.txt')
    with mock.patch.object(dispatch, 'ROOT', source):
        dispatch.private_source_links(work)
    (work / 'linked').write_text('changed')
    assert (work / 'value.txt').read_text() == 'changed'
    assert (source / 'value.txt').read_text() == 'original'


def test_nested_exchange_cancellation_reaps_observation(tmp_path):
    import subprocess
    import sys
    import time

    worker = tmp_path / 'worker.py'
    ready, reaped = tmp_path / 'ready', tmp_path / 'reaped'
    # The inner exchange has a separate session and must finish its own cleanup.
    worker.write_text('''import importlib.util
import pathlib
import signal
import subprocess
import sys
spec = importlib.util.spec_from_file_location('native_dispatch', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def terminate(signum, frame):
    raise SystemExit(143)
signal.signal(signal.SIGTERM, terminate)
try:
    module.run_provider([sys.executable, '-c',
        'import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)',
        sys.argv[2]], check=True, timeout=60)
finally:
    pathlib.Path(sys.argv[3]).write_text('reaped')
''')
    original_wait = dispatch.subprocess.Popen.wait

    def cancel_when_ready(process, timeout=None):
        if timeout == 30:
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            raise subprocess.TimeoutExpired(process.args, timeout)
        return original_wait(process, timeout=timeout)

    with mock.patch.object(dispatch.subprocess.Popen, 'wait', cancel_when_ready):
        with pytest.raises(subprocess.TimeoutExpired):
            dispatch.run_provider([sys.executable, str(worker), dispatch.__file__,
                                   str(ready), str(reaped)], check=True, timeout=30)
    assert reaped.read_text() == 'reaped'
    with pytest.raises(ProcessLookupError):
        dispatch.os.kill(int(ready.read_text()), 0)


@pytest.mark.parametrize('changed', [
    'scripts/native-services.json',
    'scripts/native-stack.schema.json',
    'services/example/runtime/requirements.txt',
    'package.json',
    'pnpm-lock.yaml',
    'tsconfig.base.json',
    'packages/contracts-example/models.py',
    'contracts/registrations/L00.json',
    'demo/example.json',
    'web/example.ts',
    'tests/lanes/L00/example.ts',
    'infra/foundation/example.py',
])
def test_shared_input_change_during_execution_rejected(tmp_path, changed):
    source, run = tmp_path / 'repository', tmp_path / 'run'
    source.mkdir()
    run.mkdir(mode=0o700)
    shared_inputs = json.loads(dispatch.MANIFEST.read_text())['shared_inputs']
    files = {
        'scripts/native-lanes.json': json.dumps({
            'selections': [], 'selection_check_operations': {},
            'dependencies': ['package.json', 'pnpm-lock.yaml'],
            'shared_inputs': shared_inputs,
            'checks': [{'id': 'web-unit', 'argv': ['test-unit']}],
        }),
        'scripts/native-services.json': json.dumps({'services': [{
            'requirements': 'services/example/runtime/requirements.txt'}]}),
        'scripts/native-stack.schema.json': '{}',
        'services/example/runtime/requirements.txt': 'example==1.0',
        'contracts/registrations/L00.json': json.dumps({'contracts': [{
            'fixtures': ['demo/example.json']}]}),
    }
    for name, content in {changed: '{}', **files}.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    original_plan = dispatch.plan
    canonical = original_plan(source)
    value = {'schema_version': 1, 'checks': canonical['checks'],
             'request_fingerprint': canonical['fingerprint']}

    def runner(argv, **options):
        # The retained snapshot still has the prior bytes when the source changes.
        assert (options['cwd'] / changed).read_text() == (source / changed).read_text()
        path = source / changed
        path.write_text('{}' if changed == 'scripts/native-services.json'
                        else path.read_text() + '\n')
        assert original_plan(source)['fingerprint'] != canonical['fingerprint']

    with mock.patch.object(dispatch, 'ROOT', source), \
            mock.patch.object(dispatch, 'plan', side_effect=lambda: original_plan(source)):
        with pytest.raises(ValueError, match='Shared source changed'):
            dispatch.shared_checks(value, canonical, run, runner)
