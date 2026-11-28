"""Route transaction contract with local source and storage substitutes."""
import asyncio
import importlib
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from reduction_local import routes
from test_reduction import fixture


class Store:
    def __init__(self):
        self.records, self.operations, self.events = {}, {}, []
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def fetchrow(self, query, key):
        table = self.operations if 'reduction_operations' in query else self.records
        return deepcopy(table.get(key))

    async def execute(self, query, *args):
        if query.startswith('INSERT INTO reduction_records'):
            key, org, subject, watch, revision, state, request, result = args
            self.records[key] = dict(id=key, organization_id=org, subject_id=subject, watch_id=watch, revision=revision, state=state, request=request, result=result)
        elif query.startswith('UPDATE reduction_records'):
            key, revision, state, result = args
            self.records[key].update(revision=revision, state=state, result=result)
        elif query.startswith('INSERT INTO reduction_operations'):
            key, record, actor, org, digest, result = args
            assert key not in self.operations
            self.operations[key] = dict(operation_id=key, record_id=record, actor_id=actor, organization_id=org, request_hash=digest, result=result)
        else:
            raise AssertionError(query)

    @asynccontextmanager
    async def transaction(self, pool, lock_key):
        async with self.lock:
            before = deepcopy((self.records, self.operations, self.events))
            try:
                yield self
            except BaseException:
                self.records, self.operations, self.events = before
                raise


class Source:
    def __init__(self):
        self.data = fixture('success')['authority']
        self.denied = False
        self.timeout = False

    @asynccontextmanager
    async def guard(self, request, record, organization, kind):
        if self.denied:
            raise HTTPException(403, detail='denied')
        if self.timeout:
            raise TimeoutError()
        data = deepcopy(self.data)
        now = datetime.now(timezone.utc)
        data['checked_at'] = (now - timedelta(seconds=1)).isoformat()
        data['valid_until'] = (now + timedelta(seconds=30)).isoformat()
        data['next_review_at'] = (now + timedelta(hours=12)).isoformat()
        if kind == 'request':
            data['actor_id'] = data['subject_id']
            data['permission'] = 'buyer_request'
        yield data


@pytest_asyncio.fixture
async def setup(monkeypatch):
    store, source = Store(), Source()
    async def enqueue(tx, event, destinations):
        tx.events.append(event.model_dump(mode='json'))
    def app():
        monkeypatch.setattr(routes, 'unit_of_work', store.transaction)
        monkeypatch.setattr(routes, 'enqueue', enqueue)
        current = FastAPI()
        current.state.pool = store
        current.state.reduction_authority = source
        @current.middleware('http')
        async def reference(request, call_next):
            request.state.request_id = 'reduction-test'
            return await call_next(request)
        current.include_router(routes.router)
        return current
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url='http://test') as client:
        yield client, store, source, app


def request_body():
    data = fixture('success')['command']
    data.update(kind='request', expected_revision=0, removed_link_ids=[], returned_link_ids=[], fit_confirmed=False)
    return data


PATH = '/v1/reduction/records/00000000-0024-4000-8000-000000000001'


@pytest.mark.asyncio
async def test_request_record_duplicate_restart_and_lookup(setup):
    client, store, source, app = setup
    body = request_body()
    created = await client.post(PATH + '/commands', json=body)
    assert created.status_code == 200
    assert created.json()['state'] == 'requested'
    assert len(store.events) == 1
    # Reloading the adapter leaves acknowledged data and operation receipts in storage.
    importlib.reload(routes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url='http://test') as restarted:
        result = await restarted.get(PATH, params={'organization_id': body['organization_id']})
        assert result.json()['record']['revision'] == 1
        # Restore the original actor to retrieve a lost request response.
        source.data['actor_id'] = body['subject_id']
        replay = await restarted.post(PATH + '/commands', json=body)
        assert replay.json() == created.json()
        assert len(store.events) == 1
        receipt = await restarted.get('/v1/reduction/operations/' + body['operation_id'], params={'record_id': PATH.rsplit('/', 1)[1], 'organization_id': body['organization_id']})
        assert receipt.json() == created.json()
        work = fixture('success')['command']
        work['operation_id'] = str(UUID(int=100))
        work['expected_revision'] = 1
        actual = await restarted.post(PATH + '/commands', json=work)
        assert actual.status_code == 200
        assert actual.json()['state'] == 'recorded'
        assert actual.json()['handover_authorized'] is False
        assert len(store.events) == 2
        duplicate = await restarted.post(PATH + '/commands', json=work)
        assert duplicate.json() == actual.json()
        assert len(store.events) == 2


@pytest.mark.asyncio
async def test_denied_timeout_stale_and_conflicting_retry(setup):
    client, store, source, _ = setup
    body = request_body()
    source.denied = True
    assert (await client.post(PATH + '/commands', json=body)).status_code == 403
    source.denied = False
    source.timeout = True
    assert (await client.post(PATH + '/commands', json=body)).status_code == 503
    assert not store.records
    source.timeout = False
    body['source_revision'] = 2
    assert (await client.post(PATH + '/commands', json=body)).status_code == 409
    body['source_revision'] = 1
    assert (await client.post(PATH + '/commands', json=body)).status_code == 200
    body['target']['value'] = '18'
    assert (await client.post(PATH + '/commands', json=body)).status_code == 409
    source.denied = True
    assert (await client.get(PATH, params={'organization_id': body['organization_id']})).status_code == 403
    assert len(store.events) == 1


@pytest.mark.asyncio
async def test_unresolved_parts_and_immutable_target(setup):
    client, store, source, _ = setup
    body = request_body()
    await client.post(PATH + '/commands', json=body)
    body = fixture('success')['command']
    body.update(operation_id=str(UUID(int=101)), expected_revision=1, returned_link_ids=[])
    response = await client.post(PATH + '/commands', json=body)
    assert response.json()['state'] == 'unresolved'
    body.update(operation_id=str(UUID(int=102)), expected_revision=2)
    body['target']['value'] = '18'
    assert (await client.post(PATH + '/commands', json=body)).status_code == 409
    assert len(store.events) == 2


@pytest.mark.asyncio
async def test_missing_provider_is_unavailable(setup):
    client, store, source, app = setup
    current = app()
    del current.state.reduction_authority
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=current), base_url='http://test') as unavailable:
        assert (await unavailable.post(PATH + '/commands', json=request_body())).status_code == 503
    assert not store.records


@pytest.mark.asyncio
async def test_outbox_failure_rolls_back_everything(setup, monkeypatch):
    client, store, source, _ = setup
    async def fail(*args):
        raise HTTPException(503)
    monkeypatch.setattr(routes, 'enqueue', fail)
    assert (await client.post(PATH + '/commands', json=request_body())).status_code == 503
    assert not store.records and not store.operations and not store.events


@pytest.mark.asyncio
async def test_absent_first_operation_is_pending(setup):
    client, store, source, _ = setup
    body = request_body()
    result = await client.get('/v1/reduction/operations/' + body['operation_id'], params={'record_id': PATH.rsplit('/', 1)[1], 'organization_id': body['organization_id']})
    assert result.status_code == 200
    assert result.json()['state'] == 'pending'
    assert not store.records and not store.operations
