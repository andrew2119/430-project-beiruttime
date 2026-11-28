import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from bt_contracts.service.cleaning.v1 import Command, Facts, Quote
from cleaning.domain import Denied, decide, readiness
from cleaning.routes import make_router
from cleaning.store import Store
import cleaning.store as storage

DATA = json.loads((Path(__file__).resolve().parents[4] / 'packages/contracts-service/cleaning/fixtures.json').read_text())
NOW = datetime.fromisoformat(DATA['now'].replace('Z', '+00:00'))


def command(**updates):
    return Command.model_validate({**deepcopy(DATA['request']), **updates})


def facts(**updates):
    return Facts.model_validate({**deepcopy(DATA['facts']), **updates})


def requested():
    return decide(command(), None, facts(), NOW)


def accepted():
    return decide(Command.model_validate(DATA['accept']), requested(), facts(quote=DATA['quote']), NOW)


@pytest.mark.parametrize('case', DATA['cases'], ids=lambda row: row['name'])
def test_contract_cases(case):
    if case['expected'] in ('requested', 'accepted'):
        assert decide(Command.model_validate(case['command']), None, Facts.model_validate(case['facts']), NOW).state == case['expected']
    else:
        with pytest.raises(Denied, match=case['expected']):
            decide(Command.model_validate(case['command']), None, Facts.model_validate(case['facts']), NOW)


@pytest.mark.parametrize('field,value', [('areas', ['movement']), ('areas', ['case', 'case']),
    ('assessment_permission', 1), ('no_submersion_promise', False), ('no_movement_service', False),
    ('expected_revision', True), ('expected_revision', -1), ('condition', ' '), ('condition', 'x'*2001)])
def test_bounded_request(field, value):
    with pytest.raises(ValidationError):
        command(**{field: value})


@pytest.mark.parametrize('field,value', [('base_minor', 1.5), ('buyer_fee_minor', False), ('total_minor', True), ('currency', 'LBP'),
    ('scope', 'full_movement_service'), ('total_minor', 1000000000000)])
def test_quote_contract(field, value):
    with pytest.raises(ValidationError):
        Quote.model_validate({**DATA['quote'], field: value})


@pytest.mark.parametrize('offset,allowed', [(-1, True), (0, False), (1, False)])
def test_preview_boundary(offset, allowed):
    expiry = datetime.fromisoformat(DATA['quote']['expires_at'].replace('Z', '+00:00'))
    if allowed:
        assert decide(Command.model_validate(DATA['accept']), requested(), facts(quote=DATA['quote']), expiry+timedelta(microseconds=offset)).state == 'accepted'
    else:
        with pytest.raises(Denied, match='quote_expired'):
            decide(Command.model_validate(DATA['accept']), requested(), facts(quote=DATA['quote']), expiry+timedelta(microseconds=offset))


@pytest.mark.parametrize('change', [{'total_minor':515000}, {'business_fee_minor':50000},
    {'assessor_id':DATA['quote']['approver_id']}, {'condition':'another condition'},
    {'request_revision':2}, {'areas':['case']}, {'buyer_id':DATA['request']['watch_id']}])
def test_assessed_scope_and_economics_cannot_expand(change):
    with pytest.raises(Denied, match='stale_quote'):
        decide(Command.model_validate(DATA['accept']), requested(), facts(quote={**DATA['quote'], **change}), NOW)


def test_acceptance_preserves_condition_and_quote_without_execution():
    record=accepted()
    assert record.condition == DATA['request']['condition']
    assert record.quote.total_minor == 500000
    assert record.quote.business_fee_minor == 25000
    with pytest.raises(Denied):
        readiness(record, facts(quote=DATA['quote']), NOW)
    with pytest.raises(Denied, match='accepted_scope_locked'):
        decide(command(expected_revision=2), record, facts(), NOW)


def ready_facts():
    q={**DATA['quote'], 'expires_at':None, 'accepted_at':DATA['now']}
    identity=DATA['request']['operation_id']
    return facts(quote=q,order_id=identity,job_id=identity,commitment_id=identity,custody_receipt_id=identity,
        payment_operation_id=identity,payment_revision=1,paid_held=True,current_custody=True,current_consent=True,incident=False,
        custody_order_id=identity,custody_watch_id=DATA['request']['watch_id'],
        commitment_order_id=identity,commitment_watch_id=DATA['request']['watch_id'],
        payment=dict(buyer_id=DATA['request']['actor_id'],order_id=identity,order_kind='service',
            watch_id=DATA['request']['watch_id'],quote_id=DATA['quote']['quote_id'],quote_revision=1,
            currency='USD',total_minor=500000,payment_operation_id=identity,payment_revision=1,state='paid_held'))


def test_retained_economics_have_no_price_expiry():
    assert readiness(accepted(), ready_facts(), NOW+timedelta(days=100))['ready'] is True


@pytest.mark.parametrize('field,value', [('order_id',None), ('job_id',None), ('commitment_id',None),
    ('custody_receipt_id',None), ('payment_operation_id',None), ('payment_revision',None),
    ('payment',None), ('custody_order_id',None), ('custody_watch_id',None),
    ('commitment_order_id',None), ('commitment_watch_id',None), ('paid_held',False), ('current_custody',False), ('current_consent',False), ('incident',True), ('source_revision',2)])
def test_execution_needs_actual_current_sources(field,value):
    with pytest.raises(Denied):
        readiness(accepted(), ready_facts().model_copy(update={field:value}), NOW)


class Pool:
    """Transaction protocol fixture, not a database durability proof."""
    def __init__(self):
        self.records={}
        self.receipts={}
        self.events=[]

    @asynccontextmanager
    async def acquire(self, **kwargs):
        yield self

    async def fetchval(self, sql, *args):
        if 'l21_cleaning_requests' in sql:
            return self.records.get(args[0])
        row=self.receipts.get(args[0])
        return row['result'] if row and row['actor_id']==args[1] and row['subject_id']==args[2] else None

    async def fetchrow(self, sql, *args):
        return self.receipts.get(args[0])

    async def execute(self, sql, *args):
        if 'INSERT INTO l21_cleaning_requests' in sql:
            self.records[args[0]]=args[1]
        if 'INSERT INTO l21_cleaning_receipts' in sql:
            self.receipts[args[0]]=dict(zip(('operation_id','actor_id','subject_id','request_hash','result'),args))



@pytest.fixture
def pool(monkeypatch):
    db=Pool()
    @asynccontextmanager
    async def transaction(pool, **kwargs):
        before=deepcopy((pool.records,pool.receipts,pool.events))
        try:
            yield pool
        except BaseException:
            pool.records,pool.receipts,pool.events=before
            raise
    async def enqueue(tx, event, destinations):
        tx.events.append(event)
    monkeypatch.setattr(storage,'unit_of_work',transaction)
    monkeypatch.setattr(storage,'enqueue',enqueue)
    return db


@pytest.mark.asyncio
async def test_lost_response_duplicate_restart_and_conflicting_receipt(pool):
    first=await Store(pool).apply(command(),facts(),lambda:NOW)
    restarted=Store(pool)
    assert await restarted.lookup(command().operation_id,command().actor_id,command().subject_id)==first
    assert await restarted.apply(command(),facts(),lambda:NOW+timedelta(seconds=1))==first
    assert len(pool.events)==1
    public=pool.events[0].model_dump_json()
    assert DATA['request']['condition'] not in public
    assert DATA['request']['preservation_limits'] not in public
    with pytest.raises(Denied,match='operation_conflict'):
        await restarted.apply(command(condition='changed'),facts(),lambda:NOW)
    with pytest.raises(Denied,match='stale_revision'):
        await restarted.apply(command(operation_id=UUID(int=17)),facts(),lambda:NOW)


@pytest.mark.asyncio
async def test_outbox_failure_rolls_back_all_acknowledged_state(pool,monkeypatch):
    async def fail(*args):
        raise OSError('unavailable')
    monkeypatch.setattr(storage,'enqueue',fail)
    with pytest.raises(OSError):
        await Store(pool).apply(command(),facts(),lambda:NOW)
    assert not pool.records and not pool.receipts and not pool.events


@pytest.mark.asyncio
async def test_route_current_authority_denial_timeout_and_duplicate(pool, tmp_path):
    actor=SimpleNamespace(actor=SimpleNamespace(subject_id=command().actor_id))
    async def principal():
        return actor
    class Provider:
        value=facts()
        unavailable=False
        @asynccontextmanager
        async def current(self,p,subject):
            if self.unavailable:
                raise TimeoutError
            yield self.value
    provider=Provider()
    app=create_app(Settings(database_url='postgresql://test:test@localhost/test', modules_path=tmp_path))
    app.include_router(make_router(Store(pool),provider,principal,lambda:NOW))
    path='/v1/cleaning/requests/'+str(command().subject_id)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post(path,json=command().model_dump(mode='json'))
        assert response.status_code==200
        stale = await client.post(path, json=command(operation_id=UUID(int=30)).model_dump(mode='json'))
        assert stale.status_code == 409
        assert stale.json()['error']['code'] == 'stale_revision'
        conflict = await client.post(path, json=command(condition='changed').model_dump(mode='json'))
        assert conflict.status_code == 409
        assert conflict.json()['error']['code'] == 'operation_conflict'
        provider.value = facts(quote={**DATA['quote'], 'expires_at': DATA['now']})
        expired = await client.post(path, json=DATA['accept'])
        assert expired.status_code == 409
        assert expired.json()['error']['code'] == 'quote_expired'
        assert str(command().operation_id) == response.json()['operation_id']
        provider.value = facts()
        provider.value=facts(authorized=False)
        assert (await client.post(path,json=command().model_dump(mode='json'))).status_code==403
        denied = await client.get(path)
        assert denied.status_code == 403
        assert denied.json()['error']['code'] == 'denied'
        lookup='/v1/cleaning/operations/'+str(command().operation_id)+'?subject_id='+str(command().subject_id)
        assert (await client.get(lookup)).status_code==403
        provider.value=facts()
        assert (await client.post(path,json=command().model_dump(mode='json'))).json()==response.json()
        provider.unavailable=True
        unavailable = await client.get(path)
        assert unavailable.status_code == 503
        assert unavailable.json()['error']['code'] == 'unavailable'
        provider.unavailable=False
        actor.actor.subject_id=UUID(int=25)
        denied = await client.get(path)
        assert denied.status_code == 403
        assert denied.json()['error']['code'] == 'denied'
        assert (await client.post(path,json=command().model_dump(mode='json'))).status_code==403


@pytest.mark.asyncio
@pytest.mark.parametrize('wait_at', ['transaction', 'operation', 'record'])
@pytest.mark.parametrize('offset,allowed', [(-1, True), (0, False), (1, False)])
async def test_acceptance_samples_time_after_all_locks(pool, monkeypatch, wait_at, offset, allowed):
    await Store(pool).apply(command(), facts(), lambda: NOW)
    expiry = datetime.fromisoformat(DATA['quote']['expires_at'].replace('Z', '+00:00'))
    current = NOW
    samples = []

    def clock():
        samples.append(current)
        return current

    def finish_wait():
        nonlocal current
        current = expiry + timedelta(microseconds=offset)

    original_transaction = storage.unit_of_work
    original_execute = pool.execute
    original_fetchval = pool.fetchval

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        async with original_transaction(*args, **kwargs) as tx:
            if wait_at == 'transaction':
                finish_wait()
            yield tx

    async def execute(sql, *args):
        if wait_at == 'operation' and 'pg_advisory_xact_lock' in sql:
            finish_wait()
        return await original_execute(sql, *args)

    async def fetchval(sql, *args):
        if wait_at == 'record' and 'FOR UPDATE' in sql:
            finish_wait()
        return await original_fetchval(sql, *args)

    monkeypatch.setattr(storage, 'unit_of_work', transaction)
    monkeypatch.setattr(pool, 'execute', execute)
    monkeypatch.setattr(pool, 'fetchval', fetchval)
    accept = Command.model_validate(DATA['accept'])
    if allowed:
        result = await Store(pool).apply(accept, facts(quote=DATA['quote']), clock)
        assert result.accepted_at == current
        assert result.next_review_at == current + timedelta(hours=24)
        # A recorded retry keeps its original result even after preview expiry.
        assert await Store(pool).apply(accept, facts(quote=DATA['quote']),
                                      lambda: expiry + timedelta(days=1)) == result
    else:
        with pytest.raises(Denied, match='quote_expired'):
            await Store(pool).apply(accept, facts(quote=DATA['quote']), clock)
        assert len(pool.receipts) == 1
        assert len(pool.events) == 1
        assert (await Store(pool).read(accept.subject_id)).state == 'requested'
    assert samples == [current]
