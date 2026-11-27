"""Communications composition remains additive and fails closed."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from bt_bulkheads import DependencyClient, Unavailable
from service_app import database
from service_app.discovery import discover
from service_app.main import create_app
from service_app.operations import OPERATIONS, destinations, pending
from bt_runtime.app.settings import Settings

ROOT = Path(__file__).resolve().parents[4]


def fragment(root, lane, *, requires=()):
    directory = root / lane
    directory.mkdir()
    name = f'{lane}_0001_notice.sql'
    (directory / name).write_text('SELECT 1;')
    (directory / 'module.json').write_text(json.dumps({
        'version': 1, 'id': f'{lane}.notice', 'requires': list(requires),
        'migrations': [name],
    }))
    return directory


def test_missing_and_concurrent_fragments(tmp_path):
    assert discover(tmp_path / 'absent') == []
    for number in range(26):
        fragment(tmp_path, f'L{number:02}')
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(discover, [tmp_path, tmp_path]))
    assert [[module.id for module in result] for result in results] == [
        [f'L{number:02}.notice' for number in range(26)]] * 2


def test_full_module_migration_dependencies(tmp_path):
    fragment(tmp_path, 'L22', requires=['L25.notice'])
    fragment(tmp_path, 'L25')
    assert [module.id for module in discover(tmp_path)] == ['L25.notice', 'L22.notice']
    steps = database.migration_steps(tmp_path)
    assert [step[0] for step in steps[-2:]] == [
        'L25.notice/L25_0001_notice.sql', 'L22.notice/L22_0001_notice.sql']
    assert len({step[0] for step in steps}) == len(steps)


def test_missing_prerequisite_and_duplicate_fail(tmp_path):
    directory = fragment(tmp_path, 'L22', requires=['L25.notice'])
    with pytest.raises(ValueError, match='prerequisite'):
        discover(tmp_path)
    duplicate = tmp_path / 'duplicate'
    duplicate.mkdir()
    (duplicate / 'module.json').write_text((directory / 'module.json').read_text())
    with pytest.raises(ValueError):
        discover(tmp_path)


def test_path_escape_and_lane_boundary(tmp_path):
    directory = fragment(tmp_path, 'L26')
    with pytest.raises(ValueError, match='Invalid module'):
        discover(tmp_path)
    data = {'version': 1, 'id': 'L22.notice', 'routes': [], 'migrations': ['../outside.sql']}
    (tmp_path / 'outside.sql').write_text('SELECT 1;')
    (directory / 'module.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='owned file'):
        discover(tmp_path)


def test_routes_are_once_and_discovery_is_service_local(tmp_path, monkeypatch):
    import re
    from bt_runtime import modules

    narrow_pattern = re.compile(r'L[01][0-9]\.[a-z-]+')
    monkeypatch.setattr(modules, 'MODULE_ID', narrow_pattern)
    fragment(tmp_path, 'L22')
    app = create_app(Settings(modules_path=tmp_path, database_url='postgresql://unused/unused'))
    assert [module.id for module in app.state.modules] == ['L22.notice']
    routes = [(method, route.path) for route in app.routes for method in getattr(route, 'methods', [])]
    assert len(routes) == len(set(routes))
    assert modules.MODULE_ID is narrow_pattern
    assert database.migration_steps(tmp_path)[-1][0].startswith('L22.notice/')


def test_manifest_preserves_existing_public_ownership():
    manifest = json.loads((ROOT / 'contracts/registrations/L22.json').read_text())
    assert (manifest['version'], manifest['lane']) == (1, 'L22')
    assert all(item['path'].startswith('packages/contracts-comms/') for item in manifest['contracts'])
    registration = (ROOT / 'web/registrations/L22.ts').read_text()
    for field in ('routes', 'navigation', 'gateway', 'slots'):
        assert f'{field}: []' in registration
    assert destinations(frozenset(), frozenset()) == ()
    with pytest.raises(ValueError, match='subscribed receiver'):
        destinations(frozenset(), frozenset(OPERATIONS))


@pytest.mark.asyncio
async def test_dependency_timeout_circuit_and_denial():
    async def slow(request):
        await asyncio.sleep(.05)
        return httpx.Response(200)
    client = DependencyClient('orders', 'http://orders', timeout=.01, failure_threshold=1,
        transport=httpx.MockTransport(slow))
    try:
        result = await client.request('POST', OPERATIONS['payment-notice.v3'].path)
        assert isinstance(result, Unavailable) and result.reason == 'timeout'
        assert (await client.request('POST', '/internal/v3/payment-notices')).reason == 'circuit_open'
        assert pending('same-operation', result.reason)['operation_id'] == 'same-operation'
        assert pending('same-operation', result.reason)['state'] == 'pending'
    finally:
        await client.aclose()
    client = DependencyClient('identity', 'http://identity',
        transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    try:
        assert (await client.request('GET', '/v1/session')).status_code == 403
        with pytest.raises(ValueError):
            await client.request('GET', '//outside/path')
    finally:
        await client.aclose()


def test_duplicate_parameterized_routes_are_rejected(tmp_path):
    directory = fragment(tmp_path, 'L22')
    (directory / 'routes.py').write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n'
        '@router.get("/v1/private/{first}")\ndef first(): return {}\n'
        '@router.get("/v1/private/{second}")\ndef second(): return {}\n')
    path = directory / 'module.json'
    data = json.loads(path.read_text())
    data['routes'] = ['routes.py:router']
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Duplicate Communications route'):
        create_app(Settings(modules_path=tmp_path, database_url='postgresql://unused/unused'))


def test_operation_freeze_and_deterministic_outcomes():
    contract = json.loads((ROOT / 'services/communications/runtime/contracts/operations.v1.json').read_text())
    operation = OPERATIONS['payment-notice.v3']
    freeze = contract['operations']['payment-notice.v3']
    assert (freeze['service'], freeze['method'], freeze['path'], freeze['timeout_seconds']) == (
        operation.service, operation.method, operation.path, operation.timeout)
    assert {row['scenario'] for row in contract['fixtures']} == {'success', 'denied', 'stale', 'lost_response'}
    assert {row['operation_id'] for row in contract['fixtures']} == {'notice-001'}
    assert all(row['synthetic'] for row in contract['fixtures'])


@pytest.mark.asyncio
async def test_per_dependency_saturation_does_not_block_another():
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(request):
        entered.set()
        await release.wait()
        return httpx.Response(200)

    first = DependencyClient('orders', 'http://orders', concurrency=1,
        transport=httpx.MockTransport(blocked))
    second = DependencyClient('identity', 'http://identity',
        transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    task = asyncio.create_task(first.request('GET', '/v1/status'))
    try:
        await entered.wait()
        assert (await first.request('GET', '/v1/status')).reason == 'saturated'
        assert (await second.request('GET', '/v1/status')).status_code == 200
    finally:
        release.set()
        await task
        await first.aclose()
        await second.aclose()


def test_concurrent_route_composition(tmp_path):
    directory = fragment(tmp_path, 'L22')
    (directory / 'routes.py').write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n'
        '@router.get("/v1/notices")\ndef notices(): return {}\n')
    path = directory / 'module.json'
    data = json.loads(path.read_text())
    data['routes'] = ['routes.py:router']
    path.write_text(json.dumps(data))

    def compose(_):
        app = create_app(Settings(modules_path=tmp_path, database_url='postgresql://unused/unused'))
        return sum(route.path == '/v1/notices' for route in app.routes)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(compose, range(2))) == [1, 1]


@pytest.mark.asyncio
async def test_runtime_health_and_private_errors_without_storage(tmp_path):
    app = create_app(Settings(modules_path=tmp_path, database_url='postgresql://unused/unused'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://communications') as client:
        async with asyncio.timeout(2):
            live = await client.get('/health/live')
            assert live.status_code == 200
            assert live.headers['cache-control'] == 'no-store'
            assert (await client.get('/health/ready')).status_code == 503
            assert (await client.post('/internal/v3/payment-notices')).status_code == 404


def test_builtin_adapter_and_migration_share_inbox_prerequisite(tmp_path):
    directory = fragment(tmp_path, 'L07')
    path = directory / 'module.json'
    data = json.loads(path.read_text())
    data['id'] = 'L07.inbox'
    path.write_text(json.dumps(data))
    app = create_app(Settings(modules_path=tmp_path, database_url='postgresql://unused/unused'))
    assert [module.id for module in app.state.modules] == ['L07.inbox', 'L22.payment-notices']
    assert sum(route.path == '/internal/v3/payment-events' for route in app.routes) == 1
    assert [step[0] for step in database.migration_steps(tmp_path)[-3:]] == [
        'L22.payment-notices/L22_0001_payment_notices.sql',
        'L22.payment-notices/L22_0002_payment_notice_recovery.sql',
        'L22.payment-notices/L22_0003_unassigned_recovery.sql',
    ]
    from bt_runtime.app import db
    assert all(not step[0].startswith('L22.') for step in db.migration_steps(tmp_path))
