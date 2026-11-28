import importlib.util
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
import pytest

ROOT = Path(__file__).resolve().parents[4]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
Store = load('recipient_store', 'services/orders/modules/payout-recipients/store.py').Store
Service = load('recipient_service', 'services/orders/modules/payout-recipients/service.py').Service
Change = load('recipient_contract', 'packages/contracts-orders/payout-recipients/v1.py').Change
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)

class Authority:
    allowed = True
    timeout = False
    age = 0
    @contextmanager
    def lease(self, actor, subject, organization, timeout_seconds):
        assert timeout_seconds == 2
        if self.timeout:
            raise TimeoutError()
        self.actor_id=actor
        yield self
    def verify(self, change, timeout_seconds):
        assert timeout_seconds == 2
        return SimpleNamespace(verified_contact=True, recipient_verified=True,
            second_factor_verified=True, reauthenticated=True, actor_id=self.actor_id, change=change,
            issued_at=NOW-timedelta(seconds=self.age), expires_at=NOW+timedelta(seconds=10))

@pytest.fixture
def setup(tmp_path):
    store=Store(tmp_path/'recipients.db')
    authority=Authority()
    service=Service(store,authority,lambda:NOW)
    subject=uuid4()
    change=Change(operation_id=uuid4(),subject_id=subject,expected_revision=0,
                  method='bank',reference='synthetic_one',proof_id=uuid4())
    return store,authority,service,subject,change

def test_restart_duplicate_and_immutable_transfer(setup):
    store,authority,service,subject,change=setup
    result=service.run('seller',subject,None,'change',change)
    assert result['state']=='succeeded'
    scope=service.scope(subject,None)
    store.bind_transfer('transfer',scope,1)
    assert service.run('seller',subject,None,'change',change)==result
    second=change.model_copy(update={'operation_id':uuid4(),'expected_revision':1,'reference':'synthetic_two'})
    assert service.run('seller',subject,None,'change',second)['revision']==2
    with pytest.raises(ValueError,match='conflict'):
        store.bind_transfer('transfer',scope,2)
    path=store.db.execute('PRAGMA database_list').fetchone()[2]
    store.db.close()
    restarted=Service(Store(path),authority,lambda:NOW)
    assert restarted.run('seller',subject,None,'lookup',operation_id=change.operation_id)==result
    assert restarted.store.db.execute('SELECT count(*) FROM outbox').fetchone()[0]==2
    assert 'synthetic_one' not in str(restarted.store.db.execute('SELECT * FROM audit').fetchall())

@pytest.mark.parametrize('age,expected',[(299,'succeeded'),(300,'denied'),(301,'denied'),(-1,'denied')])
def test_fresh_boundary(setup,age,expected):
    _,authority,service,subject,change=setup
    authority.age=age
    assert service.run('seller',subject,None,'change',change)['state']==expected

def test_stale_denied_timeout_and_conflict(setup):
    store,authority,service,subject,change=setup
    authority.timeout=True
    assert service.run('seller',subject,None,'change',change)['state']=='pending'
    authority.timeout=False
    authority.allowed=False
    for actor in ['buyer','unrelated','revoked_member']:
        assert service.run(actor,subject,None,'read')['state']=='denied'
    authority.allowed=True
    assert service.run('seller',subject,uuid4(),'change',change)['code']=='scope_mismatch'
    service.run('seller',subject,None,'change',change)
    assert service.run('other',subject,None,'lookup',operation_id=change.operation_id)['code']=='operation_conflict'
    assert service.run('seller',subject,None,'change',change.model_copy(update={'reference':'synthetic_changed'}))['code']=='operation_conflict'
    assert service.run('seller',subject,None,'change',change.model_copy(update={'operation_id':uuid4()}))['code']=='stale_revision'

@pytest.mark.parametrize('reference',['123456789','synthetic_','synthetic_'+('x'*65)])
def test_no_secret_input(setup,reference):
    *_,change=setup
    with pytest.raises(ValueError):
        Change(**{**change.model_dump(),'reference':reference})

@pytest.mark.parametrize('offset,expected',[(-1,'denied'),(0,'denied'),(1,'succeeded')])
def test_proof_expiry(setup,offset,expected):
    _,authority,service,subject,change=setup
    original=authority.verify
    def verify(command,timeout_seconds):
        proof=original(command,timeout_seconds)
        proof.expires_at=NOW+timedelta(seconds=offset)
        return proof
    authority.verify=verify
    assert service.run('seller',subject,None,'change',change)['state']==expected

@pytest.mark.parametrize('field',['second_factor_verified','reauthenticated','verified_contact','recipient_verified','actor_id','change'])
def test_bound_factors(setup,field):
    _,authority,service,subject,change=setup
    original=authority.verify
    def verify(command,timeout_seconds):
        proof=original(command,timeout_seconds)
        setattr(proof,field,False)
        return proof
    authority.verify=verify
    assert service.run('seller',subject,None,'change',change)['code']=='verification_required'

def test_contract_fixtures():
    import json
    Result=load('recipient_result','packages/contracts-orders/payout-recipients/v1.py').Result
    data=json.loads((ROOT/'packages/contracts-orders/payout-recipients/fixtures.json').read_text())
    for case in data['cases']:
        Result(**{key:value for key,value in case.items() if key!='name'})

def test_private_adapter(setup):
    from fastapi import FastAPI
    import asyncio
    from httpx import AsyncClient, ASGITransport
    _,authority,service,subject,change=setup
    adapter=load('recipient_adapter','services/orders/modules/payout-recipients/adapter.py')
    actor=SimpleNamespace(actor_id='seller',subject_id=subject,organization_id=None)
    app=FastAPI()
    async def principal():
        return actor
    app.include_router(adapter.router_for(service,principal,Change))
    async def exercise():
      async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/internal/v1/payout-recipients')).json()['revision']==0
        assert (await client.post('/internal/v1/payout-recipients',content=change.model_dump_json())).json()['state']=='succeeded'
        result=(await client.get('/internal/v1/payout-recipients/operations/'+str(change.operation_id))).json()
        assert result['recipient_version']==1
        assert (await client.post('/internal/v1/payout-recipients',json={'secret':'never-retained'})).json()['code']=='invalid_request'
        assert (await client.post('/internal/v1/payout-recipients',content='x'*2049)).json()['code']=='request_too_large'
        authority.allowed=False
        assert (await client.get('/internal/v1/payout-recipients')).json()['state']=='denied'

    asyncio.run(exercise())


@pytest.mark.parametrize('elapsed,expected', [(0, 'succeeded'), (1, 'denied'), (2, 'denied')])
def test_verification_completion_uses_current_time(setup, elapsed, expected):
    store, authority, service, subject, change = setup
    authority.age = 299
    instant = [NOW]
    service.clock = lambda: instant[0]
    original = authority.verify

    def verify(command, timeout_seconds):
        proof = original(command, timeout_seconds)
        instant[0] += timedelta(seconds=elapsed)
        return proof

    authority.verify = verify
    result = service.run('seller', subject, None, 'change', change)
    assert result['state'] == expected
    assert store.current(service.scope(subject, None))['revision'] == (1 if expected == 'succeeded' else 0)

def test_complete_envelope_on_every_service_path(setup):
    store, authority, service, subject, change = setup
    Result = load('recipient_envelope', 'packages/contracts-orders/payout-recipients/v1.py').Result
    required = {
        'schema_version', 'operation_id', 'subject_id', 'watch_id', 'actor_id',
        'organization_id', 'expected_revision', 'state', 'revision',
        'pending_reason', 'next_actor', 'next_review_at',
    }

    def check(value):
        assert required <= value.keys()
        Result.model_validate(value)
        assert value['watch_id'] is None
        assert value['actor_id'] == 'seller'
        if value['state'] == 'pending':
            assert value['next_actor'] == 'seller'
            assert datetime.fromisoformat(value['next_review_at']) == NOW + timedelta(hours=24)
        else:
            assert value['next_actor'] is None
            assert value['next_review_at'] is None
            assert value['pending_reason'] is None
        return value

    assert check(service.run('seller', subject, None, 'read'))['operation_id'] is None
    unknown = check(service.run('seller', subject, None, 'lookup', operation_id=change.operation_id))
    assert unknown['expected_revision'] is None
    authority.timeout = True
    pending = check(service.run('seller', subject, None, 'change', change))
    assert pending['operation_id'] == str(change.operation_id)
    assert pending['expected_revision'] == 0
    authority.timeout = False
    authority.allowed = False
    check(service.run('seller', subject, None, 'change', change))
    authority.allowed = True
    result = check(service.run('seller', subject, None, 'change', change))
    assert check(service.run('seller', subject, None, 'change', change)) == result
    assert check(service.run('seller', subject, None, 'lookup', operation_id=change.operation_id)) == result
    stored = __import__('json').loads(store.db.execute('SELECT result FROM operations').fetchone()[0])
    assert stored == result
    outbox = __import__('json').loads(store.db.execute('SELECT body FROM outbox').fetchone()[0])
    assert outbox == result
    stale = change.model_copy(update={'operation_id': uuid4()})
    assert check(service.run('seller', subject, None, 'change', stale))['code'] == 'stale_revision'


def test_unparsed_response_envelope():
    adapter = load('recipient_error_envelope', 'services/orders/modules/payout-recipients/adapter.py')
    Result = load('recipient_error_result', 'packages/contracts-orders/payout-recipients/v1.py').Result
    actor = SimpleNamespace(actor_id='seller', subject_id=uuid4(), organization_id=None)
    value = adapter.envelope({'state': 'denied', 'code': 'invalid_request'}, actor)
    Result.model_validate(value)
    assert value['operation_id'] is None
    assert value['expected_revision'] is None
    assert value['watch_id'] is None
    assert value['next_actor'] is None
    assert value['next_review_at'] is None


def test_database_contention_returns_pending_and_recovers(setup):
    import asyncio
    import sqlite3
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport

    store, _, service, subject, change = setup
    adapter = load('recipient_busy_adapter', 'services/orders/modules/payout-recipients/adapter.py')
    Result = load('recipient_busy_result', 'packages/contracts-orders/payout-recipients/v1.py').Result
    actor = SimpleNamespace(actor_id='seller', subject_id=subject, organization_id=None)
    app = FastAPI()

    async def principal():
        return actor

    app.include_router(adapter.router_for(service, principal, Change))
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    store.db.execute('PRAGMA busy_timeout=10')
    blocker = sqlite3.connect(path, isolation_level=None)
    root = '/internal/v1/payout-recipients'

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            blocker.execute('BEGIN IMMEDIATE')
            try:
                for method, url, body, expected_operation, expected_revision in [
                    ('GET', root, None, None, None),
                    ('GET', root + '/operations/' + str(change.operation_id), None, str(change.operation_id), None),
                    ('POST', root, change.model_dump_json(), str(change.operation_id), 0),
                ]:
                    response = await client.request(method, url, content=body)
                    assert response.status_code == 200
                    value = response.json()
                    Result.model_validate(value)
                    assert value['state'] == 'pending'
                    assert value['pending_reason'] == 'store_unavailable'
                    assert value['operation_id'] == expected_operation
                    assert value['expected_revision'] == expected_revision
                    assert value['next_actor'] == 'seller'
                    assert datetime.fromisoformat(value['next_review_at']) == NOW + timedelta(hours=24)
                    assert not store.db.in_transaction
                assert store.db.execute('SELECT count(*) FROM operations').fetchone()[0] == 0
            finally:
                blocker.execute('ROLLBACK')
            result = (await client.post(root, content=change.model_dump_json())).json()
            assert result['state'] == 'succeeded'
            blocker.execute('BEGIN IMMEDIATE')
            try:
                pending = (await client.get(root + '/operations/' + str(change.operation_id))).json()
                assert pending['state'] == 'pending'
                assert pending['operation_id'] == str(change.operation_id)
            finally:
                blocker.execute('ROLLBACK')
            assert (await client.get(root + '/operations/' + str(change.operation_id))).json() == result
            assert (await client.post(root, content=change.model_dump_json())).json() == result
            assert store.db.execute('SELECT count(*) FROM outbox').fetchone()[0] == 1

    try:
        asyncio.run(exercise())
    finally:
        blocker.close()
