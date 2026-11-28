import importlib
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from bt_runtime.app.db import migration_steps
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from conftest import ROOT


def test_full_inventory_registers_each_operation_once(runtime):
    service, _ = runtime
    main = importlib.import_module('service_app.main')
    settings = Settings(service_name=service, database_url='postgresql://unused/test',
                        modules_path=ROOT / 'services' / service / 'modules')
    app = main.create_app(settings)
    operations = [(method, route.path) for route in app.routes for method in getattr(route, 'methods', [])]
    assert len(operations) == len(set(operations))
    assert any(m.id.startswith('L14.') for m in app.state.modules)
    assert app.state.settings.service_name == service
    if service == 'pricing':
        assert ('GET', '/v1/quotes/{quote_id}') in operations
        for action, method in [('validation', 'GET'), ('retained', 'GET'), ('commit', 'POST')]:
            assert (method, '/internal/v3/quotes/{quote_id}/' + action) in operations
        for path in ('/v1/offers', '/v1/brand-quotes', '/v1/repair-quotes'):
            assert ('POST', path) in operations
    else:
        assert 'auction.proxy.v1' in app.state.hooks
        assert 'auction.proxy.v2' in app.state.hooks
        assert ('POST', '/v1/auctions') in operations


def test_additive_migration_plan_is_stable_and_complete(runtime):
    service, _ = runtime
    root = ROOT / 'services' / service / 'modules'
    steps = migration_steps(root)
    names = [name for name, _, _ in steps]
    assert len(names) == len(set(names))
    files = {p.resolve() for p in root.rglob('migrations/*.sql')}
    registered = {p for module in discover(root) for p in module.migrations}
    assert files == registered
    assert all(len(checksum) == 64 for _, checksum, _ in steps)
    if service == 'pricing':
        assert names.index('L07.quotes/L07_0001_quotes.sql') < names.index('L14.a-current/L14_0001_current.sql')
        assert names.index('L14.a-current/L14_0001_current.sql') < names.index('L14.offers/L14_0001_offers.sql')
    else:
        assert names.index('L05.a-rules/L05_0001_rules.sql') < names.index('L14.a-kernel/L14_0001_kernel.sql')


def test_lane_range_absence_concurrency_and_duplicate_rejection(runtime, tmp_path):
    assert discover(tmp_path / 'absent') == []
    for lane in ('L00', 'L12', 'L14', 'L25'):
        directory = tmp_path / lane
        directory.mkdir()
        (directory / 'module.json').write_text(json.dumps({'version': 1, 'id': lane + '.example'}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: [m.id for m in discover(tmp_path)], range(4)))
    assert all(result == ['L00.example', 'L12.example', 'L14.example', 'L25.example'] for result in results)
    duplicate = tmp_path / 'duplicate'
    duplicate.mkdir()
    (duplicate / 'module.json').write_text(json.dumps({'version': 1, 'id': 'L14.example'}))
    with pytest.raises(ValueError, match='Duplicate'):
        discover(tmp_path)
    (duplicate / 'module.json').write_text(json.dumps({'version': 1, 'id': 'L26.example'}))
    with pytest.raises(ValueError, match='Invalid'):
        discover(duplicate)


def test_packaging_rejects_escape_before_writing(runtime, tmp_path):
    _, discovery = runtime
    root = tmp_path / 'repository'
    (root / 'contracts/registrations').mkdir(parents=True)
    (root / 'packages/contracts-example').mkdir(parents=True)
    manifest = {'version': 1, 'lane': 'L25', 'contracts': [
        {'namespace': 'example.current.v1', 'path': '../outside', 'fixtures': []}]}
    (root / 'contracts/registrations/L25.json').write_text(json.dumps(manifest))
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='existing package'):
        discovery.package_contracts(root, output)
    assert not output.exists()


def test_unsubscribed_destinations_stay_disabled():
    manifest = json.loads((ROOT / 'contracts/registrations/L14.json').read_text())
    assert all(not item['enabled'] for item in manifest['wiring']['destinations'].values())
    fixtures = manifest['wiring']['fixtures']
    assert {item['state'] for item in fixtures} == {'succeeded', 'denied', 'stale', 'pending'}
    assert len({item['operation_id'] for item in fixtures}) == 1
