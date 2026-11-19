"""Provider envelopes bind canonical inputs without executing suites."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from test_isolation import native


def available():
    return Mock(return_value={
        'schema_version': 1, 'capabilities': dict.fromkeys(native.REQUIRED, True),
        'published_contracts_read_only': True})


def test_service_envelope_and_private_publication():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / 'source'
        root.mkdir()
        for name in ('services/identity/runtime', 'services/identity/modules',
                     'tests/foundation', 'tests/lanes/L00', 'contracts', 'scripts'):
            (root / name).mkdir(parents=True)
        (root / 'scripts/native-runtime-tests.py').touch()
        request = {'schema_version': 1, 'operation': 'runtime-layout',
                   'source_root': str(root), 'service': 'identity', 'lane': 'L00',
                   'run_dir': str(Path(folder) / 'run')}
        with patch.object(native, 'protected_executable'):
            result = native.provider_layout(request, backend=available())
        assert result['request_fingerprint'] == native.digest(request)
        assert '/lane-tests' not in result['mappings']
        assert result['working_directory'] == '/app'
        assert result['artifacts'] == {'inputs': [], 'outputs': []}
        destination = Path(folder) / 'private/layout.json'
        native.write_private(destination, result, root)
        assert destination.stat().st_mode & 0o777 == 0o600
        assert json.loads(destination.read_text()) == result
        try:
            native.write_private(destination, result, root)
        except native.IsolationError:
            pass
        else:
            raise AssertionError('Existing output accepted')


def test_all_canonical_topologies_and_mutations():
    plan = native.canonical_plan(native.ROOT)
    with patch.object(native, 'safe_input', side_effect=lambda root, name: str(root / name)), \
            patch.object(native, 'protected_executable'), \
            patch.object(native, 'canonical_plan', return_value=plan):
        for selection in plan['selections']:
            result = native.provider_layout(selection, backend=available())
            assert result['topology'] == selection['topology']
            assert result['request_fingerprint'] == selection['request_fingerprint']
            assert result['import_roots'] == [str(native.ROOT / name)
                                              for name in selection['topology']['import_roots']]
            assert result['mappings']['/app'].endswith(selection['topology']['runtime'])
            assert '/lane-tests' not in result['mappings']
            changed = dict(selection, sources=['services'])
            try:
                native.provider_layout(changed, backend=available())
            except native.IsolationError:
                pass
            else:
                raise AssertionError('Noncanonical selection accepted')


def test_backend_deadlines_and_missing_installation():
    with patch.object(Path, 'is_file', return_value=True), \
            patch.object(Path, 'is_symlink', return_value=False), \
            patch.object(Path, 'stat', return_value=Mock(st_uid=0, st_mode=0o100755)), \
            patch.object(native.subprocess, 'run', return_value=Mock(stdout='{}')) as run:
        native.installed_backend({'operation': 'check'})
        assert run.call_args.kwargs['timeout'] == 60
        native.installed_backend({'operation': 'run'})
        assert 600 <= run.call_args.kwargs['timeout'] <= 610
    with patch.object(Path, 'is_file', return_value=False):
        try:
            native.check_backend()
        except native.IsolationError as error:
            assert 'missing' in str(error)
        else:
            raise AssertionError('Missing installation accepted')


def test_private_output_rejects_links_and_public_parents():
    with tempfile.TemporaryDirectory() as folder:
        parent = Path(folder)
        public = parent / 'public'
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        link = parent / 'alias'
        link.symlink_to(public)
        for destination in (link / 'layout.json', public / 'layout.json'):
            try:
                native.write_private(destination, {}, parent / 'source')
            except native.IsolationError:
                pass
            else:
                raise AssertionError('Unsafe output accepted')
        assert not list(public.iterdir())
        assert os.getuid() == parent.stat().st_uid


def test_service_provider_writes_both_requested_destinations():
    with tempfile.TemporaryDirectory() as folder:
        parent = Path(folder)
        request = {'schema_version': 1, 'operation': 'runtime-layout',
                   'source_root': str(parent / 'source'), 'service': 'identity',
                   'lane': 'L00', 'run_dir': str(parent / 'run')}
        envelope = {'source_root': request['source_root'], 'schema_version': 1}
        request_file = parent / 'request.json'
        request_file.write_text(json.dumps(request))
        result_file = parent / 'response.json'
        with patch.object(native, 'provider_layout', return_value=envelope):
            native.provide(request_file, result_file)
        for output in (result_file, parent / 'run/identity/layout.json'):
            assert json.loads(output.read_text()) == envelope
            assert output.stat().st_mode & 0o777 == 0o600


def test_hardlinked_source_rejected():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'contracts').mkdir()
        original = root / 'contracts/example.json'
        original.write_text('{}')
        os.link(original, root / 'alias.json')
        try:
            native.safe_input(root, 'contracts')
        except native.IsolationError:
            pass
        else:
            raise AssertionError('Hardlinked input accepted')
