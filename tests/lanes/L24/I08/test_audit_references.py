import copy
import importlib.util
import json
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from bt_contracts_core.errors import AccessDenied, PublicError
from pydantic import ValidationError
from bt_bulkheads import DependencyClient, Unavailable
from bt_runtime.principal import CurrentPrincipal, current_principal as identity_principal

ROOT = Path(__file__).resolve().parents[4]
CONTRACT = ROOT / 'packages/contracts-comms/audit-references'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


models = load('bt_contracts.comms.audit_references.models', CONTRACT / 'models.py')
routes = load('l24_audit_routes', ROOT / 'services/communications/modules/audit-references/routes.py')
fixture = json.loads((CONTRACT / 'fixtures.json').read_text())
ORG = fixture['query']['organization_id']
READER = fixture['success']['reader_id']


def principal(**changes):
    value = {'actor': {'subject_id': READER, 'organization_id': ORG, 'session_id': 'current'},
             'roles': ['operator'], 'permissions': [], 'organizations': [ORG],
             'organization_grants': [{'organization_id': ORG, 'roles': [], 'permissions': ['audit.references.read']}]}
    value.update(changes)
    return CurrentPrincipal.model_validate(value)


class Owner:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else fixture['success']
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self.status == 'timeout':
            return Unavailable('owner', 'timeout')
        if self.status == 'slow':
            import asyncio
            await asyncio.sleep(2)
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def app(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)

    @app.exception_handler(AccessDenied)
    async def denied(request, exc):
        return JSONResponse({'error': {'code': 'denied'}}, status_code=403)

    @app.exception_handler(PublicError)
    async def error(request, exc):
        return JSONResponse({'error': {'code': exc.code}}, status_code=exc.status)
    app.state.audit_reference_clients = {name: Owner() for name in (*routes.SOURCES, 'identity')}

    @app.middleware('http')
    async def context(request, call_next):
        request.state.request_id = 'read-reference'
        return await call_next(request)

    async def current(*args):
        return principal()

    monkeypatch.setattr(routes, 'current_principal', current)
    return app


async def get(app, path='/v1/audit-references', params=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        return await client.get(path, params=params or fixture['query'], headers={'Authorization': 'Bearer synthetic'})


@pytest.mark.asyncio
async def test_independent_sources_and_no_fallback(app):
    app.state.audit_reference_clients['orders'].status = 'timeout'
    answer = await get(app)
    assert answer.status_code == 200
    assert [r['state'] for r in answer.json()['results']] == ['ready', 'unavailable', 'ready']
    assert answer.headers['cache-control'] == 'no-store'
    for source in routes.SOURCES:
        calls = app.state.audit_reference_clients[source].calls
        assert len(calls) == 1 and calls[0][1] == '/internal/v1/audit-references'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,state', [(202, 'pending'), (403, 'denied'), (409, 'stale'), (404, 'unavailable'), ('slow', 'unavailable')])
async def test_owner_states(app, status, state):
    app.state.audit_reference_clients['trust'].status = status
    answer = await get(app, params={**fixture['query'], 'source': 'trust'})
    assert answer.json()['results'] == [{'source': 'trust', 'state': state, 'page': None}]


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'roles': ['buyer']}, {'roles': ['reviewer']}, {'organization_grants': []}, {'organizations': []}])
async def test_current_permission_denies_before_owner_read(app, monkeypatch, changes):
    async def current(*args):
        return principal(**changes)
    monkeypatch.setattr(routes, 'current_principal', current)
    assert (await get(app)).status_code == 403
    assert all(not app.state.audit_reference_clients[s].calls for s in routes.SOURCES)


@pytest.mark.asyncio
async def test_wrong_organization_and_revocation_during_read(app, monkeypatch):
    q = {**fixture['query'], 'organization_id': '90000000-0000-4000-8000-000000000001'}
    assert (await get(app, params=q)).status_code == 403
    count = 0

    async def current(*args):
        nonlocal count
        count += 1
        return principal(organization_grants=[] if count > 1 else principal().model_dump()['organization_grants'])
    monkeypatch.setattr(routes, 'current_principal', current)
    assert (await get(app)).status_code == 403


@pytest.mark.asyncio
async def test_lost_response_duplicate_and_restart_requery(app):
    first = await get(app)
    second = await get(app)
    assert first.json() == second.json()
    app.state.audit_reference_clients = {name: Owner() for name in (*routes.SOURCES, 'identity')}
    assert (await get(app)).json() == first.json()


@pytest.mark.asyncio
@pytest.mark.parametrize('alter', ['private', 'reader', 'organization', 'duplicate', 'query', 'revision'])
async def test_malformed_owner_page_is_unavailable(app, alter):
    body = copy.deepcopy(fixture['success'])
    if alter == 'private':
        body['items'][0]['evidence'] = 'restricted'
    elif alter == 'reader':
        body['reader_id'] = '90000000-0000-4000-8000-000000000001'
    elif alter == 'organization':
        body['items'][0]['organization_id'] = '90000000-0000-4000-8000-000000000001'
    elif alter == 'duplicate':
        body['items'] *= 2
        body['total'] = 2
    elif alter == 'query':
        body['query']['limit'] = 50
    elif alter == 'revision':
        body['query']['expected_revision'] = 2
    app.state.audit_reference_clients['trust'].body = body
    result = (await get(app)).json()['results'][0]
    assert result == {'source': 'trust', 'state': 'unavailable', 'page': None}


@pytest.mark.asyncio
async def test_lookup_binding_and_stale(app):
    row = copy.deepcopy(fixture['success']['items'][0])
    app.state.audit_reference_clients['trust'].body = row
    path = '/v1/audit-references/operations/' + row['operation_id']
    params = {'source': 'trust', 'organization_id': ORG, 'expected_revision': row['revision']}
    assert (await get(app, path, params)).json()['item'] == row
    params['expected_revision'] = 1
    result = (await get(app, path, params)).json()
    assert result['state'] == 'stale' and result['item'] is None
    row['operation_id'] = fixture['query']['operation_id']
    result = (await get(app, path, params)).json()
    assert result['state'] == 'unavailable' and result['item'] is None


@pytest.mark.parametrize('instant,valid', [('2026-10-31T23:59:59Z', False), ('2026-11-01T00:00:00Z', True), ('2026-11-01T00:00:01Z', True), ('2026-11-01T23:59:59Z', True), ('2026-11-02T00:00:00Z', False), ('2026-11-02T00:00:01Z', False)])
def test_date_boundaries(instant, valid):
    body = copy.deepcopy(fixture['success'])
    body['items'][0]['occurred_at'] = instant
    if valid:
        models.OwnerPage.model_validate_json(json.dumps(body))
    else:
        with pytest.raises(ValidationError):
            models.OwnerPage.model_validate_json(json.dumps(body))


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [{'limit': '51'}, {'offset': '10001'}, {'before': '2026-11-01T00:00:00Z'}, {'before': '2026-12-03T00:00:00Z'}, {'after': '2026-11-01T01:00:00+01:00'}, {'evidence': 'restricted'}, {'limit': '1.1'}])
async def test_request_budgets(app, change):
    assert (await get(app, params={**fixture['query'], **change})).status_code == 422


def test_real_pagination_thousand_rows():
    template = fixture['success']
    seen = set()
    for offset in range(0, 1000, 20):
        body = copy.deepcopy(template)
        body['query']['offset'] = offset
        body['total'] = 1000
        body['next_offset'] = offset + 20 if offset < 980 else None
        body['items'] = [{**template['items'][0], 'operation_id': str(UUID(int=1000-i))} for i in range(offset, offset+20)]
        page = models.OwnerPage.model_validate_json(json.dumps(body))
        seen.update(r.operation_id for r in page.items)
    assert len(seen) == 1000


def test_schema_and_pending_responsibility():
    schema = json.loads((CONTRACT / 'schema.json').read_text())
    assert schema == {'query': models.AuditQuery.model_json_schema(), 'page': models.OwnerPage.model_json_schema(), 'operation': models.AuditReference.model_json_schema()}
    row = {**fixture['success']['items'][0], 'state': 'pending'}
    with pytest.raises(ValidationError):
        models.AuditReference.model_validate_json(json.dumps(row))


@pytest.mark.asyncio
async def test_three_source_panels_share_bounded_identity_without_shedding(app, monkeypatch):
    import asyncio
    holder = FastAPI()
    dependencies = routes.clients(holder)
    identity = dependencies['identity']
    assert isinstance(identity, DependencyClient)
    assert 3 <= identity.concurrency <= 4
    await identity.client.aclose()
    active = 0
    peak = 0

    async def reply(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.02)
            return httpx.Response(200, json=principal().model_dump(mode='json'))
        finally:
            active -= 1

    identity.client = httpx.AsyncClient(transport=httpx.MockTransport(reply), base_url='http://identity')
    app.state.audit_reference_clients['identity'] = identity
    monkeypatch.setattr(routes, 'current_principal', identity_principal)
    try:
        answers = await asyncio.gather(*(get(app, params={**fixture['query'], 'source': source}) for source in routes.SOURCES))
        assert all(answer.status_code == 200 and answer.json()['results'][0]['state'] == 'ready' for answer in answers)
        assert peak == 3
    finally:
        for dependency in dependencies.values():
            await dependency.aclose()
