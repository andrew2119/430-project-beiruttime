import concurrent.futures
import json
from pathlib import Path
import runpy
import shutil
import subprocess

import pytest
from bt_runtime.app.settings import Settings
from service_app.discovery import discover
from service_app.main import create_app, migration_steps


def input_root(test_file, image_root=Path('/wiring-inputs')):
    for parent in test_file.resolve().parents:
        if (parent / 'services/trust/runtime/run_tests.py').is_file():
            return parent
    if (image_root / 'services/trust/runtime/run_tests.py').is_file():
        return image_root
    raise FileNotFoundError('Trust wiring test inputs are missing')


ROOT = input_root(Path(__file__))


def test_input_resolution_supports_both_layouts(tmp_path):
    checkout = tmp_path / 'checkout'
    runner = checkout / 'services/trust/runtime/run_tests.py'
    runner.parent.mkdir(parents=True)
    runner.write_text('')
    assert input_root(checkout / 'tests/lanes/L18/WIRE-L18/test_wiring.py') == checkout
    image = tmp_path / 'wiring-inputs'
    image_runner = image / 'services/trust/runtime/run_tests.py'
    image_runner.parent.mkdir(parents=True)
    image_runner.write_text('')
    assert input_root(Path('/lane-tests/L18/WIRE-L18/test_wiring.py'), image) == image
    with pytest.raises(FileNotFoundError, match='inputs are missing'):
        input_root(tmp_path / 'missing/test_wiring.py', tmp_path / 'absent')


@pytest.mark.parametrize('lane', [f'L{number:02}' for number in range(26)])
def test_runtime_runner_accepts_supported_lanes(monkeypatch, lane):
    calls = []
    monkeypatch.setenv('BT_TEST_LANE', lane)
    monkeypatch.setattr(pytest, 'main', lambda args: calls.append(args) or 0)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / 'services/trust/runtime/run_tests.py'))
    assert result.value.code == 0
    assert len(calls) == 1
    assert '/lane-tests/L00' in calls[0]
    if lane != 'L00':
        assert f'/lane-tests/{lane}' in calls[0]


@pytest.mark.parametrize('lane', ['L26', 'L99', 'L1', 'L18/../L00', ''])
def test_runtime_runner_rejects_unsupported_lanes(monkeypatch, lane):
    monkeypatch.setenv('BT_TEST_LANE', lane)
    monkeypatch.setattr(pytest, 'main', lambda args: pytest.fail('Invalid lane reached tests'))
    with pytest.raises(SystemExit, match='BT_TEST_LANE must be L00 through L25'):
        runpy.run_path(str(ROOT / 'services/trust/runtime/run_tests.py'))


def module(root, lane, *, dependencies=(), routes=()):
    folder = root / lane
    folder.mkdir()
    name = f'{lane}.sample'
    migration = f'{lane}_0001_sample.sql'
    (folder / migration).write_text('SELECT 1;')
    (folder / 'module.json').write_text(json.dumps({
        'version': 1, 'id': name, 'migrations': [migration],
        'migration_dependencies': list(dependencies), 'routes': list(routes),
    }))
    return folder


def settings(root):
    return Settings(service_name='trust', database_url='postgresql://unused', modules_path=root)


def test_every_lane_and_absent_fragments(tmp_path):
    assert discover(tmp_path / 'absent') == []
    for number in range(26):
        module(tmp_path, f'L{number:02}')
    assert len(discover(tmp_path)) == 26
    assert len(migration_steps(tmp_path)) >= 26
    module(tmp_path, 'L26')
    with pytest.raises(ValueError, match='Invalid module'):
        discover(tmp_path)


def test_full_module_dependencies_and_missing_provider(tmp_path):
    module(tmp_path, 'L18', dependencies=['L25.sample'])
    with pytest.raises(ValueError, match='absent'):
        discover(tmp_path)
    module(tmp_path, 'L25')
    assert [item.id for item in discover(tmp_path)] == ['L25.sample', 'L18.sample']
    assert [name for name, _, _ in migration_steps(tmp_path) if '/L' in name] == [
        'L25.sample/L25_0001_sample.sql', 'L18.sample/L18_0001_sample.sql']
    registration = tmp_path / 'L25/module.json'
    data = json.loads(registration.read_text())
    data['migration_dependencies'] = ['L18.sample']
    registration.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Cyclic'):
        discover(tmp_path)


def test_path_escape_and_duplicate_ids(tmp_path):
    folder = module(tmp_path, 'L18')
    registration = folder / 'module.json'
    data = json.loads(registration.read_text())
    data['migrations'] = ['../L18_0001_outside.sql']
    registration.write_text(json.dumps(data))
    (tmp_path / 'L18_0001_outside.sql').write_text('SELECT 1;')
    with pytest.raises(ValueError, match='owned file'):
        discover(tmp_path)
    data['migrations'] = []
    registration.write_text(json.dumps(data))
    duplicate = tmp_path / 'duplicate'
    duplicate.mkdir()
    (duplicate / 'module.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Duplicate module'):
        discover(tmp_path)


def test_parallel_composition_preserves_foundation(tmp_path):
    from bt_runtime.modules import MODULE_ID
    module(tmp_path, 'L18')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        apps = list(pool.map(lambda _: create_app(settings(tmp_path)), range(4)))
    assert all([item.id for item in app.state.modules] == ['L18.sample'] for app in apps)
    assert not MODULE_ID.fullmatch('L18.sample')
    assert len({id(app) for app in apps}) == 4


def test_duplicate_routes_fail_before_start(tmp_path):
    for lane in ('L18', 'L19'):
        folder = module(tmp_path, lane, routes=['routes.py:router'])
        (folder / 'routes.py').write_text(
            'from fastapi import APIRouter\nrouter = APIRouter()\n'
            '@router.get("/v1/sample")\nasync def read():\n    return {}\n')
    with pytest.raises(ValueError, match='Duplicate route'):
        create_app(settings(tmp_path))


def test_fragment_preserves_existing_public_registrations():
    # No contract exports: omit the fragment until shared consumers admit L18.
    assert not (ROOT / 'contracts/registrations/L18.json').exists()
    web = (ROOT / 'web/registrations/L18.ts').read_text()
    for field in ('routes', 'gateway', 'slots'):
        assert f'{field}: []' in web
    deployment = json.loads((ROOT / 'infra/railway/trust.json').read_text())
    assert 'service_app.main:create_app' in deployment['deploy']['startCommand']


def test_existing_contract_consumers_accept_absent_fragment(tmp_path):
    discover_contracts = runpy.run_path(
        str(ROOT / 'infra/foundation/discover-contracts.py'))['discover']
    expected = discover_contracts(ROOT)
    # Mirror inputs; generated indexes belong only to the temporary tree.
    (tmp_path / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
    shutil.copytree(ROOT / 'contracts', tmp_path / 'contracts')
    web = tmp_path / 'web'
    (web / 'scripts').mkdir(parents=True)
    shutil.copy2(ROOT / 'web/scripts/generate-nav.mjs', web / 'scripts/generate-nav.mjs')
    shutil.copytree(ROOT / 'web/registrations', web / 'registrations')
    subprocess.run(['node', str(web / 'scripts/generate-nav.mjs')],
                   check=True, capture_output=True, text=True, timeout=30)
    assert json.loads((web / 'contracts.generated.json').read_text()) == expected
    index = (web / 'registry.generated.ts').read_text()
    assert index.count("from './registrations/L18'") == 1


def test_service_identity_is_not_interchangeable(tmp_path):
    with pytest.raises(ValueError, match='authoritative service name'):
        create_app(Settings(service_name='orders', database_url='postgresql://unused', modules_path=tmp_path))


@pytest.mark.asyncio
async def test_dependency_timeout_circuit_and_denial_are_not_success():
    import asyncio
    import httpx
    from bt_bulkheads import DependencyClient, Unavailable

    async def slow(request):
        await asyncio.sleep(.05)
        return httpx.Response(200, json={'state': 'accepted'})

    dependency = DependencyClient('identity', 'http://identity', timeout=.01,
                                  failure_threshold=1, concurrency=1,
                                  transport=httpx.MockTransport(slow))
    try:
        first = await dependency.request('GET', '/v1/current')
        assert isinstance(first, Unavailable) and first.reason == 'timeout'
        second = await dependency.request('GET', '/v1/current')
        assert isinstance(second, Unavailable) and second.reason == 'circuit_open'
    finally:
        await dependency.aclose()
    denied = DependencyClient('identity', 'http://identity', transport=httpx.MockTransport(
        lambda request: httpx.Response(403, json={'state': 'denied'})))
    try:
        result = await denied.request('GET', '/v1/current')
        assert result.status_code == 403
        assert result.json()['state'] == 'denied'
        with pytest.raises(ValueError, match='relative'):
            await denied.request('GET', '//other/v1/current')
    finally:
        await denied.aclose()
