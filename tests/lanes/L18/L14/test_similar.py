import asyncio
import importlib.util
import json
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location('similar', ROOT / 'services/catalog/modules/similar-watches/service.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def watch(number=1, **changes):
    return dict(id=UUID(int=number), watch_id=UUID(int=number + 10000), revision=1,
                title='ساعة Sample ⌚', brand='Sample', reference='R1', price_minor=500000,
                currency='USD', available=True, sample=True, **changes) if not changes else {**watch(number), **changes}


class Provider:
    def __init__(self, rows):
        self.rows = rows

    async def current_public(self):
        return self.rows


def query(**changes):
    return module.Query(**{**dict(operation_id=UUID(int=9000), subject_id=UUID(int=1), expected_revision=1), **changes})


def run(rows, **changes):
    return asyncio.run(module.find(Provider(rows), query(**changes)))


def test_priority_and_disclosure():
    result = run([watch(), watch(2, reference='different'), watch(3, brand='Other'), watch(4)])
    assert [item.rule for item in result.items] == ['reference', 'brand', 'price_band']
    assert [item.watch.id.int for item in result.items] == [4, 2, 3]
    assert result.total == 3


@pytest.mark.parametrize('price,matched', [(399999, False), (400000, True), (400001, True),
                                          (599999, True), (600000, True), (600001, False), (None, False)])
def test_band_boundaries(price, matched):
    result = run([watch(), watch(2, brand='Other', price_minor=price)])
    assert (result.total == 1) is matched


def test_empty_missing_and_normalization():
    assert run([watch()]).state == 'empty'
    assert run([]).state == 'denied'
    assert run([watch(), watch(2, brand='Other', price_minor=None)]).state == 'empty'
    assert run([watch(), watch(2, brand=' SAMPLE ', reference=' r1 ')]).items[0].rule == 'reference'
    assert run([watch(reference=''), watch(2, reference='')]).items[0].rule == 'brand'


def test_stale_and_duplicate_physical_watch():
    assert run([watch(revision=2), watch(2)]).state == 'stale'
    assert run([watch(), watch(2, watch_id=watch()['watch_id'])]).state == 'empty'
    result = run([watch(), watch(2), watch(3, watch_id=watch(2)['watch_id'])])
    assert result.total == 1
    assert run([watch(), watch()]).state == 'unavailable'


@pytest.mark.parametrize('field,value', [('organization_id', 'other'), ('actor_id', 'other'), ('offset', 1),
                                         ('expected_revision', True), ('expected_revision', 0)])
def test_closed_scope_and_bounds(field, value):
    with pytest.raises(ValueError):
        query(**{field: value})


@pytest.mark.parametrize('price', [True, 1.5, float('inf'), -1, 1000000000001])
def test_exact_money(price):
    assert run([watch(), watch(2, price_minor=price)]).state == 'unavailable'


def test_complete_pagination_and_stable_retries():
    rows = [watch(i) for i in range(1, 1002)]
    first = run(rows)
    assert first.total == 1000 and len(first.items) == 20 and first.next_offset == 20
    assert run(list(reversed(rows))) == first
    ids = []
    for offset in range(0, 1000, 20):
        page = run(rows, offset=offset)
        ids.extend(item.watch.id for item in page.items)
    assert len(ids) == len(set(ids)) == 1000
    assert run(rows + [watch(1002)]).state == 'unavailable'


def test_timeout_restart_and_current_scope_recheck():
    class Slow:
        async def current_public(self):
            await asyncio.sleep(2)
    pending = asyncio.run(module.find(Slow(), query()))
    assert pending.state == 'unavailable' and pending.operation_id == query().operation_id
    recovered = run([watch(), watch(2)])
    assert recovered == run([watch(), watch(2)])
    assert recovered.operation_id == pending.operation_id
    assert run([watch()]).state == 'empty'
    assert run([]).state == 'denied'


def test_public_fixture_schema():
    path = ROOT / 'packages/contracts-catalog/similar-watches/fixtures.json'
    fixtures = json.loads(path.read_text())
    assert set(fixtures) == {'success', 'empty', 'denied', 'stale', 'lost_response'}
    for value in fixtures.values():
        module.Result.model_validate(value)


@pytest.mark.asyncio
async def test_route_lookup_and_closed_parameters():
    import importlib
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    routes = importlib.import_module('services.catalog.modules.similar-watches.routes')
    rows = [watch(), watch(2)]
    app = FastAPI()
    app.include_router(routes.create_router(lambda _: Provider(rows)))
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    address = f'/v1/similar-watches/{UUID(int=1)}'
    params = dict(operation_id=str(UUID(int=9000)), expected_revision='1')
    response = await client.get(address, params=params)
    assert response.status_code == 200
    assert response.json()['state'] == 'ready'
    assert (await client.get(address, params=params)).json() == response.json()
    for extra in ({'organization_id': 'other'}, {'actor_id': 'other'}, {'expected_revision': '1.0'}, {'offset': '1'}):
        assert (await client.get(address, params={**params, **extra})).status_code == 422
    assert (await client.get(address, params=[*params.items(), ('operation_id', str(UUID(int=9000)))])).status_code == 422
    rows.clear()
    assert (await client.get(address, params=params)).json()['state'] == 'denied'
    await client.aclose()


def test_current_private_seller_scope():
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    provider_module = importlib.import_module('services.catalog.modules.similar-watches.provider')
    source = SimpleNamespace(id=UUID(int=1), seller_id=UUID(int=2), revision=1, seller_type='private')
    class Connection:
        async def fetch(self, _sql):
            return [source]
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    class Pool:
        def acquire(self, **_kwargs):
            return Connection()
    from unittest.mock import patch
    with patch.object(provider_module, 'parse_row', lambda row: row):
        for decision in (None, {'listing_id':source.id,'seller_id':source.seller_id,'listing_revision':2,'eligible':True}):
            provider = provider_module.PublicProvider(Pool(), None, AsyncMock(return_value=decision) if decision else None)
            assert asyncio.run(module.find(provider, query())).state == 'unavailable'
        deny = dict(listing_id=source.id, seller_id=source.seller_id, listing_revision=1, eligible=False)
        provider = provider_module.PublicProvider(Pool(), None, AsyncMock(return_value=deny))
        assert asyncio.run(module.find(provider, query())).state == 'denied'


def test_public_unavailable_anchor_and_available_candidates():
    result = run([watch(available=False), watch(2), watch(3, available=False)])
    assert result.state == 'ready' and result.total == 1
    assert result.items[0].watch.id.int == 2


def test_published_schemas_validate_documents():
    jsonschema = pytest.importorskip("jsonschema", reason="Schema validator unavailable in the pinned environment")
    path = ROOT / 'packages/contracts-catalog/similar-watches'
    schema = json.loads((path / 'result.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    for fixture in json.loads((path / 'fixtures.json').read_text()).values():
        jsonschema.validate(fixture, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'state': 'invented'}, schema)
    query_schema = json.loads((path / 'query.schema.json').read_text())
    jsonschema.validate(query().model_dump(mode='json'), query_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**query().model_dump(mode='json'), 'organization_id': 'other'}, query_schema)
