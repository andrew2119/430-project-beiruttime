"""Route commands with deterministic transaction and current-authority substitutes."""
import asyncio
import copy
import importlib.util
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4
import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def setup(monkeypatch):
    actor, org = uuid4(), uuid4()
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=actor, organization_id=org))
    state = {'person': person, 'allowed': True, 'timeout': False, 'records': {}, 'serials': {}, 'drafts': [], 'events': [], 'checks': 0, 'revoke_at': None}

    class Error(Exception):
        def __init__(self, code, message, status): self.code, self.status = code, status

    async def principal(request):
        state['checks'] += 1
        if state['checks'] == state['revoke_at']: state['allowed'] = False
        if not state['allowed']: raise Error('denied', '', 403)
        return state['person']

    async def upstream(*args):
        if state['timeout']: raise Error('unavailable', '', 503)
        return dict(id=str(org), kind='dealer', state='active', platform_onboarded=True, authenticated_business=True, capabilities=['sales'], public_name='Sample')

    async def emit(tx, request, row, kind): state['events'].append(row['id'])

    class Tx:
        async def fetchrow(self, sql, *args):
            if sql.startswith('SELECT'): return state['records'].get(args[0])
            state['drafts'].append(args[0]);return {'id':args[0]}
        async def fetchval(self, sql, *args): return state['serials'].get(args[0])
        async def execute(self, sql, *args):
            if sql.startswith('INSERT INTO catalog_dealer_import_serials'): state['serials'][args[0]]=args[1]
            if sql.startswith('INSERT INTO catalog_dealer_imports('):
                state['records'][args[0]]=dict(actor_id=args[1], organization_id=args[2], digest=args[3], result=args[4])

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        before=copy.deepcopy(state)
        try: yield Tx()
        except Exception:
            state.clear();state.update(before);raise

    for name, values in {
        'modules.listings.dependencies':dict(principal=principal,seller_scope=lambda p:None,upstream=upstream),
        'modules.listings.repository':dict(emit=emit),
        'bt_contracts_core.errors':dict(PublicError=Error),
        'bt_runtime.app.db':dict(unit_of_work=transaction),
    }.items():
        module=ModuleType(name);module.__dict__.update(values);monkeypatch.setitem(sys.modules,name,module)
    spec=importlib.util.spec_from_file_location('dealer_import', ROOT/'services/catalog/modules/dealer-import/routes.py',submodule_search_locations=[str(ROOT/'services/catalog/modules/dealer-import')])
    module=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,'dealer_import',module);spec.loader.exec_module(module)
    payload=b'brand,model,reference,year,condition,location,price_usd,serial\nSample,Sample,R1,2020,Used,Beirut,5000.00,S1\n'

    def request(key='operation-1', revision='0', body=payload):
        async def stream(): yield body
        return SimpleNamespace(headers={'Idempotency-Key':key,'If-Match':revision},stream=stream,app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    return module,state,request,Error


def test_lost_response_restart_duplicate_and_scope(setup):
    module,state,request,Error=setup
    first=asyncio.run(module.create(request()))
    assert first['items'][0]['state']=='draft' and len(state['events'])==1
    assert asyncio.run(module.create(request()))==first
    assert len(state['drafts'])==1
    second=asyncio.run(module.create(request(key='operation-2')))
    assert second['items'][0]==dict(row=1,state='duplicate',listing_id=None)
    assert len(state['drafts'])==1
    state['person']=SimpleNamespace(actor=SimpleNamespace(subject_id=uuid4(),organization_id=state['person'].actor.organization_id))
    with pytest.raises(Error) as error: asyncio.run(module.create(request()))
    assert error.value.status==403


def test_stale_denied_timeout_and_conflict(setup):
    module,state,request,Error=setup
    with pytest.raises(Error) as error: asyncio.run(module.create(request(revision='1')))
    assert error.value.status==409
    state['allowed']=False
    with pytest.raises(Error): asyncio.run(module.create(request()))
    state['allowed']=True;state['timeout']=True
    with pytest.raises(Error): asyncio.run(module.create(request()))
    assert not state['drafts']
    state['timeout']=False
    asyncio.run(module.create(request()))
    with pytest.raises(Error) as error: asyncio.run(module.create(request(body=b'brand,model,reference,year,condition,location,price_usd,serial\nSample,Sample,R1,2020,Used,Beirut,5000.00,S2\n')))
    assert error.value.code=='operation_conflict'


@pytest.mark.parametrize('checkpoint', [2, 3, 4])
def test_revoked_scope_rolls_back_admission(setup, checkpoint):
    module, state, request, Error = setup
    state['revoke_at'] = checkpoint
    with pytest.raises(Error) as error:
        asyncio.run(module.create(request()))
    assert error.value.status == 403
    assert not state['drafts']
    assert not state['events']
    assert not state['records']
    assert not state['serials']


def test_revocation_during_upload(setup):
    module, state, request, Error = setup
    upload = request()
    original = upload.stream

    async def stream():
        async for chunk in original():
            yield chunk
        state['allowed'] = False

    upload.stream = stream
    with pytest.raises(Error) as error:
        asyncio.run(module.create(upload))
    assert error.value.status == 403
    assert not state['drafts']


def test_persisted_batch_envelope(setup):
    module, state, request, _ = setup
    result = asyncio.run(module.create(request()))
    assert result['actor_id'] == str(state['person'].actor.subject_id)
    assert result['organization_id'] == str(state['person'].actor.organization_id)
    assert result['expected_revision'] == 0
    for field in ['subject_id', 'watch_id', 'pending_reason', 'next_actor', 'next_review_at']:
        assert field in result and result[field] is None
    retained = json.loads(state['records'][result['operation_id']]['result'])
    assert retained == {k: v for k, v in result.items() if k not in ['offset', 'limit']}


def test_scope_change_during_upload(setup):
    module, state, request, Error = setup
    upload = request()
    original = upload.stream

    async def stream():
        async for chunk in original():
            yield chunk
        state['person'] = SimpleNamespace(actor=SimpleNamespace(
            subject_id=state['person'].actor.subject_id, organization_id=uuid4()))

    upload.stream = stream
    with pytest.raises(Error):
        asyncio.run(module.create(upload))
    assert not state['drafts']
    assert not state['records']
