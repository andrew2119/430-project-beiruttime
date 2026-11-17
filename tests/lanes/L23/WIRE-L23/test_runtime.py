import concurrent.futures
import json
from pathlib import Path

import pytest
from service_app.modules import Module, discover
from service_app.main import create_app
from bt_runtime.app.settings import Settings


ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / 'contracts/registrations/L23.json').is_file()
)


def fragment(root, lane, name='example'):
    folder = root / f'{lane}-{name}'
    folder.mkdir()
    migration = f'{lane}_0001_example.sql'
    (folder / migration).write_text('SELECT 1;')
    (folder / 'module.json').write_text(json.dumps({
        'version': 1, 'id': f'{lane}.{name}', 'migrations': [migration],
    }))
    return folder


def test_absent_and_all_lanes(tmp_path):
    assert discover(tmp_path / 'absent') == []
    for lane in reversed(range(26)):
        fragment(tmp_path, f'L{lane:02}')
    modules = discover(tmp_path)
    assert [item.id for item in modules] == [f'L{lane:02}.example' for lane in range(26)]
    assert sum(len(item.migrations) for item in modules) == 26
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(discover, [tmp_path] * 4))
    assert all(result == modules for result in results)


def test_composed_migration_plan_is_additive_and_dependency_ordered(tmp_path, monkeypatch):
    import asyncio
    import hashlib
    import shutil
    from contextlib import asynccontextmanager

    from bt_runtime.app import db, main
    from service_app import migrate

    # Restore the shared composition after exercising the service entrypoints.
    monkeypatch.setattr(main, 'discover', main.discover)
    monkeypatch.setattr(db, 'discover', db.discover)
    # Route and worker implementations are outside this pure migration-plan check.
    from fastapi import APIRouter

    async def idle_worker(app):
        return None

    def load_entrypoint(module, reference):
        assert (module.root / reference.partition(':')[0]).is_file()
        return idle_worker if reference in module.workers else APIRouter()

    monkeypatch.setattr(Module, 'load', load_entrypoint)
    source = ROOT / 'services/service-operations/modules'
    shutil.copytree(source, tmp_path / 'modules')
    modules_path = tmp_path / 'modules'
    settings = Settings(database_url='postgresql://test-unused', modules_path=modules_path,
                        service_name='service-operations')
    create_app(settings)
    retained = db.migration_steps(modules_path)
    expected = [(path.name, hashlib.sha256(path.read_bytes()).hexdigest(), path.read_text())
                for path in sorted(db.MIGRATIONS.glob('*.sql'))]
    for module in discover(source):
        expected.extend((module.id + '/' + path.name,
                         hashlib.sha256(path.read_bytes()).hexdigest(), path.read_text())
                        for path in module.migrations)
    assert retained == expected
    assert 'L09.intake/L09_0001_intake.sql' in [step[0] for step in retained]
    assert 'L09.intake/L09_0002_private_evidence.sql' in [step[0] for step in retained]
    assert 'L11.directory/L11_0001_directory.sql' in [step[0] for step in retained]

    # Create dependants first so filesystem creation order cannot supply the plan.
    additions = [
        ('L25', 'CREATE TABLE test_review (id integer REFERENCES test_work(id));'),
        ('L23', 'CREATE TABLE test_work (id integer PRIMARY KEY, '
         'intake_id uuid REFERENCES technical_intakes(id), '
         'organization_id uuid REFERENCES directory_profiles(organization_id));'),
    ]
    for lane, sql in additions:
        folder = fragment(modules_path, lane)
        (folder / f'{lane}_0001_example.sql').write_text(sql)
    app = create_app(settings)
    plan = db.migration_steps(modules_path)
    assert plan[:len(retained)] == retained
    expected_additions = [
        (f'{lane}.example/{lane}_0001_example.sql',
         hashlib.sha256(sql.encode()).hexdigest(), sql)
        for lane, sql in reversed(additions)
    ]
    assert plan == retained + expected_additions
    assert [module.id for module in app.state.modules] == [
        'L09.intake', 'L11.directory', 'L23.example', 'L25.example',
    ]
    keys = [step[0] for step in plan]
    assert len(keys) == len(set(keys))
    assert keys.index('L09.intake/L09_0001_intake.sql') < keys.index(
        'L09.intake/L09_0002_private_evidence.sql')
    assert keys.index('L11.directory/L11_0001_directory.sql') < keys.index(
        'L23.example/L23_0001_example.sql') < keys.index('L25.example/L25_0001_example.sql')
    assert db.migrate.__globals__['migration_steps'] is db.migration_steps

    class Ledger:
        async def fetch(self, query):
            return [{'step_id': key, 'checksum': checksum} for key, checksum, _ in plan]

        @asynccontextmanager
        async def acquire(self, **kwargs):
            yield self

    assert asyncio.run(db.ready(Ledger(), modules_path))
    captured = []

    async def capture_migration(url, path):
        assert url == settings.database_url
        captured.append(db.migration_steps(path))

    monkeypatch.setattr(migrate, 'Settings', lambda: settings)
    monkeypatch.setattr(db, 'migrate', capture_migration)
    migrate.run()
    assert captured == [plan]


def test_rejects_outside_range_and_duplicates(tmp_path):
    folder = fragment(tmp_path, 'L26')
    with pytest.raises(ValueError, match='Invalid module'):
        discover(tmp_path)
    (folder / 'module.json').unlink()
    fragment(tmp_path, 'L23')
    duplicate = fragment(tmp_path, 'L23', 'other')
    data = json.loads((duplicate / 'module.json').read_text())
    data['id'] = 'L23.example'
    (duplicate / 'module.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Duplicate module'):
        discover(tmp_path)


def test_migration_cannot_escape_or_cross_lane(tmp_path):
    folder = fragment(tmp_path, 'L23')
    data = json.loads((folder / 'module.json').read_text())
    (tmp_path / 'L23_0002_escape.sql').write_text('SELECT 2;')
    data['migrations'] = ['../L23_0002_escape.sql']
    (folder / 'module.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='owned file'):
        discover(tmp_path)
    (folder / 'L24_0001_wrong.sql').write_text('SELECT 1;')
    data['migrations'] = ['L24_0001_wrong.sql']
    (folder / 'module.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='their lane'):
        discover(tmp_path)


def test_route_collision_is_rejected(tmp_path):
    for lane in ['L00', 'L25']:
        folder = fragment(tmp_path, lane)
        (folder / 'routes.py').write_text(
            'from fastapi import APIRouter\nrouter = APIRouter()\n'
            '@router.get("/v1/example")\ndef read():\n    return {}\n')
        data = json.loads((folder / 'module.json').read_text())
        data['routes'] = ['routes.py:router']
        (folder / 'module.json').write_text(json.dumps(data))
    settings = Settings(database_url='postgresql://unused', modules_path=tmp_path,
                        service_name='service-operations')
    with pytest.raises(ValueError, match='Duplicate route'):
        create_app(settings)


def test_registration_adds_no_duplicate_public_surface():
    data = json.loads((ROOT / 'contracts/registrations/L23.json').read_text())
    assert data == {'version': 1, 'lane': 'L23', 'contracts': []}
    text = (ROOT / 'web/registrations/L23.ts').read_text()
    for field in ['routes', 'gateway', 'slots', 'navigation']:
        assert f'{field}: []' in text


@pytest.mark.asyncio
async def test_dependency_timeout_circuit_and_isolation():
    import asyncio
    import httpx
    from bt_bulkheads import DependencyClient, Unavailable

    async def slow(request):
        await asyncio.sleep(.1)
        return httpx.Response(200, json={})

    timed = DependencyClient('identity', 'http://identity', timeout=.01,
                             failure_threshold=1, transport=httpx.MockTransport(slow))
    healthy = DependencyClient('orders', 'http://orders',
                               transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    try:
        result = await timed.request('GET', '/internal/v1/principal')
        assert isinstance(result, Unavailable) and result.reason == 'timeout'
        result = await timed.request('GET', '/internal/v1/principal')
        assert isinstance(result, Unavailable) and result.reason == 'circuit_open'
        assert (await healthy.request('GET', '/internal/v1/readiness')).status_code == 403
    finally:
        await timed.aclose()
        await healthy.aclose()


@pytest.mark.asyncio
async def test_dependency_budget_sheds_without_queueing():
    import asyncio
    import httpx
    from bt_bulkheads import DependencyClient, Unavailable

    entered, finish = asyncio.Event(), asyncio.Event()

    async def blocked(request):
        entered.set()
        await finish.wait()
        return httpx.Response(200)

    client = DependencyClient('orders', 'http://orders', concurrency=1,
                              transport=httpx.MockTransport(blocked))
    first = asyncio.create_task(client.request('GET', '/internal/v1/readiness'))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        result = await client.request('GET', '/internal/v1/readiness')
        assert isinstance(result, Unavailable) and result.reason == 'saturated'
        finish.set()
        assert (await first).status_code == 200
    finally:
        finish.set()
        await first
        await client.aclose()
