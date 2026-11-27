"""Pure registration and runtime boundary checks, without external services."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from types import SimpleNamespace

import httpx
import pytest
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import migration_steps
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from service_app.app import create_app
from service_app.catalog_dependencies import clients, upstream
from service_app.discovery import configure

def layout(test_file):
    """Find the complete checkout or packaged test inputs without fixed depth."""
    for root in Path(test_file).resolve().parents:
        for modules in (root / 'services/catalog/modules', root / 'app/modules'):
            if (modules.is_dir()
                    and (root / 'contracts/registrations/L15.json').is_file()
                    and (root / 'web/registrations/L15.ts').is_file()):
                return root, modules
    raise RuntimeError('Catalog test modules, manifest and registration source are required')


ROOT, MODULES = layout(__file__)
MANIFEST = json.loads((ROOT / 'contracts/registrations/L15.json').read_text())


@pytest.mark.parametrize('packaged', [False, True])
def test_layout_inputs(tmp_path, packaged):
    root = tmp_path / 'image'
    modules = root / ('app/modules' if packaged else 'services/catalog/modules')
    modules.mkdir(parents=True)
    for relative in ('contracts/registrations/L15.json', 'web/registrations/L15.ts'):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
    test_file = root / ('lane-tests/L15/WIRE-L15/test_wiring.py' if packaged
                        else 'tests/lanes/L15/WIRE-L15/test_wiring.py')
    assert layout(test_file) == (root, modules)
    (root / 'web/registrations/L15.ts').unlink()
    with pytest.raises(RuntimeError, match='registration source'):
        layout(test_file)


def test_full_composition_and_migration_plan():
    configure()
    app = create_app(Settings(database_url='postgresql://unused', service_name='catalog', modules_path=MODULES))
    pairs = [(method, route.path) for route in app.routes for method in getattr(route, 'methods', ())]
    assert len(pairs) == len(set(pairs))
    assert set(MANIFEST['runtime']['module_ids']) <= {module.id for module in app.state.modules}
    steps = [name for name, _, _ in migration_steps(MODULES)]
    assert len(steps) == len(set(steps))
    assert steps.index('L03.listings/L03_0001_listings.sql') < steps.index(
        'L03.media/L03_0001_media.sql')
    assert steps.index('L08.request-drafts/L08_0001_request_drafts.sql') < steps.index(
        'L15.request-submissions/L15_0001_submitted_requests.sql')
    assert steps.index('L15.listing-revisions/L15_0001_listing_revisions.sql') < steps.index(
        'L15.listing-revisions/L15_0002_listing_edit_protocol.sql')
    # Gateway parameters may have different names; their URL shapes must agree.
    def normalize(path):
        return re.sub(r'\{[^}]+\}|:[a-z_]+', ':id', path)
    source = (ROOT / 'web/registrations/L15.ts').read_text()
    for path in re.findall(r"path:'(/v1/[^']+)'", source):
        for version in ('v1', 'v2'):
            assert normalize(path.replace('/v1/', f'/{version}/')) in {normalize(p) for _, p in pairs}
    assert '/internal/' not in source


def test_absent_concurrent_and_invalid_fragments(tmp_path):
    configure()
    assert discover(tmp_path / 'absent') == []
    for lane in range(26):
        folder = tmp_path / f'L{lane:02}'
        folder.mkdir()
        (folder / 'module.json').write_text(json.dumps({'version': 1, 'id': f'L{lane:02}.example'}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(discover, [tmp_path] * 2))
    assert [m.id for m in results[0]] == [m.id for m in results[1]]
    assert len(results[0]) == 26
    duplicate = tmp_path / 'duplicate'
    duplicate.mkdir()
    (duplicate / 'module.json').write_text(json.dumps({'version': 1, 'id': 'L15.example'}))
    with pytest.raises(ValueError, match='Duplicate'):
        discover(tmp_path)
    (duplicate / 'module.json').write_text(json.dumps({'version': 1, 'id': 'L26.example'}))
    with pytest.raises(ValueError, match='Invalid'):
        discover(tmp_path)


@pytest.mark.asyncio
async def test_per_dependency_budgets_and_pending_recovery():
    app = SimpleNamespace(state=SimpleNamespace())
    owned = clients(app)
    try:
        assert clients(app) is owned
        for name, client in owned.items():
            assert client.dependency == name
            budget = MANIFEST['runtime']['dependency_budget']
            assert (client.timeout, client.concurrency, client.failure_threshold, client.cooldown) == (
                budget['timeout_seconds'], budget['concurrency'], budget['failure_threshold'], budget['cooldown_seconds'])
        assert owned['orders'] is not owned['identity']
    finally:
        await asyncio.gather(*(client.aclose() for client in owned.values()))
    for fixture in MANIFEST['runtime']['fixtures']:
        if fixture['state'] == 'pending':
            assert fixture['next_action'] == 'retry_same_operation'
    assert all(set(message) == {'en', 'ar'} for message in MANIFEST['runtime']['recovery']['messages'].values())


@pytest.mark.asyncio
async def test_timeout_saturation_circuit_and_recovery():
    entered, release = asyncio.Event(), asyncio.Event()

    async def remote(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={'revision': 2})

    client = DependencyClient('orders', 'http://orders', timeout=.02, concurrency=1,
                              failure_threshold=1, cooldown=.01, transport=httpx.MockTransport(remote))
    try:
        first = asyncio.create_task(client.request('GET', '/internal/v1/example'))
        await entered.wait()
        assert (await client.request('GET', '/internal/v1/example')).reason == 'saturated'
        assert (await first).reason == 'timeout'
        assert (await client.request('GET', '/internal/v1/example')).reason == 'circuit_open'
        await asyncio.sleep(.02)
        release.set()
        assert (await client.request('GET', '/internal/v1/example')).json() == {'revision': 2}
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('result,exception,status', [
    (Unavailable('orders', 'timeout'), PublicError, 503),
    (httpx.Response(403), AccessDenied, None),
    (httpx.Response(409), PublicError, 409),
    (httpx.Response(200, content=b'invalid'), PublicError, 503),
])
async def test_adapter_fails_closed(result, exception, status):
    class Stub:
        async def request(self, *args, **kwargs):
            return result

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(catalog_clients={'orders': Stub()})),
                              query_params={}, headers={}, state=SimpleNamespace(request_id='example'))
    with pytest.raises(exception) as caught:
        await upstream(request, 'orders', 'GET', '/internal/v1/example')
    if status:
        assert caught.value.status == status


def test_contract_packaging_bounds_and_missing_fragments(tmp_path):
    from service_app.contract_package import package, registrations

    assert registrations(tmp_path) == []
    fragments = tmp_path / 'contracts/registrations'
    fragments.mkdir(parents=True)
    source = tmp_path / 'packages/contracts-example/scope'
    source.mkdir(parents=True)
    (source / 'v1.py').write_text('VERSION = 1\n')
    fragment = fragments / 'L25.json'
    data = {'version': 1, 'lane': 'L25', 'contracts': [
        {'namespace': 'example.scope.v1', 'path': 'packages/contracts-example/scope'}]}
    fragment.write_text(json.dumps(data))
    package(tmp_path, tmp_path / 'output')
    assert (tmp_path / 'output/bt_contracts/example/scope/v1.py').read_text() == 'VERSION = 1\n'
    data['contracts'][0]['path'] = '../outside'
    fragment.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Contract path'):
        registrations(tmp_path)
    data['contracts'][0]['path'] = 'packages/contracts-example/scope'
    data['contracts'] *= 2
    fragment.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='namespace'):
        registrations(tmp_path)
