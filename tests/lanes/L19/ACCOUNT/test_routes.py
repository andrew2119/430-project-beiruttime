"""Pure adapter checks with deterministic authority and transactional storage substitutes."""
import asyncio
import copy
import importlib.util
import json
import sys
import types
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[4]
ACTOR = UUID('00000000-0000-0000-0000-000000000001')
LISTING = UUID('00000000-0000-0000-0000-000000000002')
FACTS = dict(subject_id=str(ACTOR), organization_id=None, seller_status='approved', watch_id='watch-1', watch_revision=1, listing_revision=1)


class Store:
    def __init__(self):
        self.storage_ready = True
        self.proof = None
        self.receipts = {}
        self.photos = []
        self.events = []
        self.now = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)

    async def fetchrow(self, sql, *args):
        if 'possession_receipts' in sql:
            return self.receipts.get((args[0], args[1]))
        return {'proof': self.proof} if self.proof else None

    async def fetchval(self, sql):
        if 'to_regclass' in sql:
            return self.storage_ready
        assert sql == 'SELECT clock_timestamp()'
        return self.now

    async def execute(self, sql, *args):
        if 'INSERT INTO identity_l19_possession(' in sql:
            self.proof = args[2]
        elif 'INSERT INTO identity_l19_possession_receipts' in sql:
            self.receipts[(args[0], args[1])] = dict(digest=args[2], result=args[3])
        elif 'INSERT INTO identity_l19_possession_photos' in sql:
            self.photos.append(args)
        else:
            raise AssertionError(sql)


@pytest.fixture
def adapter(monkeypatch):
    package = types.ModuleType('l19_private'); package.__path__ = [str(ROOT/'services/identity/modules/private-seller')]
    monkeypatch.setitem(sys.modules, 'l19_private', package)
    identity = types.ModuleType('service_app.identity')
    async def live_actor(tx, request, **kwargs):
        if not request.app.state.active:
            from bt_contracts_core.errors import PublicError
            raise PublicError('unauthorized', 'Sign in again.', status=401)
        return {'id':ACTOR}, None
    identity.live_actor = live_actor
    monkeypatch.setitem(sys.modules, 'service_app.identity', identity)
    spec = importlib.util.spec_from_file_location('l19_private.possession_routes', ROOT/'services/identity/modules/private-seller/possession_routes.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    store = Store()
    @asynccontextmanager
    async def transaction(pool):
        snapshot = copy.deepcopy(pool.__dict__)
        try:
            yield pool
        except BaseException:
            pool.__dict__ = snapshot
            raise
    async def enqueue(tx, event, destinations):
        tx.events.append((event, destinations))
    monkeypatch.setattr(module, 'unit_of_work', transaction)
    monkeypatch.setattr(module, 'live_actor', live_actor)
    monkeypatch.setattr(module, 'enqueue', enqueue)
    # Exercise decoding directly; event-loop thread wakeups require a separate process check.
    async def decode_call(function, *args):
        return function(*args)
    monkeypatch.setattr(module.asyncio, 'to_thread', decode_call)
    return module, store


def request(store, provider=None, key='issue-0001', active=True):
    state = types.SimpleNamespace(pool=store, active=active)
    if provider is not None:
        state.listing_possession_authority = provider
    return Request({'type':'http','method':'POST','path':'/','headers':[(b'idempotency-key',key.encode())],
        'app':types.SimpleNamespace(state=state),'state':{'request_id':'request-1'}})


class Provider:
    def __init__(self, facts=None): self.facts = dict(FACTS if facts is None else facts)
    async def current(self, actor, listing):
        assert actor == str(ACTOR) and listing == str(LISTING)
        return self.facts


@pytest.mark.asyncio
async def test_lost_response_retry_restart_and_changed_body(adapter):
    module, store = adapter
    first = await module.command('issue', LISTING, module.Issue(expected_revision=0), request(store,Provider()))
    retry = await module.command('issue', LISTING, module.Issue(expected_revision=0), request(store,Provider()))
    assert first == retry
    assert len(store.receipts) == 1
    with pytest.raises(Exception) as caught:
        await module.command('issue', LISTING, module.Issue(expected_revision=1), request(store,Provider()))
    assert caught.value.code == 'operation_conflict'
    assert json.loads(store.proof)['revision'] == 1


@pytest.mark.asyncio
async def test_missing_provider_denied_and_revocation_never_replay_success(adapter):
    module, store = adapter
    for provider, active, code in [(None,True,'unavailable'),(Provider(dict(FACTS,organization_id='other-business')),True,'forbidden'),(Provider(),False,'unauthorized')]:
        with pytest.raises(Exception) as caught:
            await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,provider,active=active))
        assert caught.value.code == code
        assert not store.receipts and store.proof is None
    await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,Provider()))
    with pytest.raises(Exception) as caught:
        await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,Provider(dict(FACTS,seller_status='suspended'))))
    assert caught.value.code == 'forbidden'


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', sorted(FACTS))
async def test_incomplete_authority_writes_nothing(adapter, missing):
    module, store = adapter
    facts = {key: value for key, value in FACTS.items() if key != missing}
    with pytest.raises(Exception) as caught:
        await module.command('issue', LISTING, module.Issue(expected_revision=0), request(store, Provider(facts)))
    assert caught.value.code == 'unavailable'
    assert store.proof is None
    assert not store.photos and not store.receipts and not store.events


@pytest.mark.asyncio
async def test_timeout_and_stale_provider_leave_no_success(adapter):
    module, store = adapter
    class Timeout:
        async def current(self,*args): raise TimeoutError()
    with pytest.raises(Exception) as caught:
        await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,Timeout()))
    assert caught.value.code == 'unavailable'
    assert store.proof is None
    await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,Provider()))
    with pytest.raises(Exception) as caught:
        await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,Provider(dict(FACTS,listing_revision=2))))
    assert caught.value.code == 'stale_proof'


@pytest.mark.asyncio
async def test_submission_photo_and_outbox_commit_once_with_receipt(adapter):
    module,store = adapter
    issued = (await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,Provider())))['proof']
    import base64
    import io
    from PIL import Image
    photo=io.BytesIO();Image.new('RGB',(8,8)).save(photo,format='PNG')
    body=module.Submission(expected_revision=1,challenge_id=issued['challenge_id'],code=issued['code'],photo_base64=base64.b64encode(photo.getvalue()).decode(),safe_photo=True,synthetic_photo=True)
    result=await module.command('submit',LISTING,body,request(store,Provider(),'submit-0001'))
    assert result['proof']['state']=='pending'
    assert await module.command('submit',LISTING,body,request(store,Provider(),'submit-0001'))==result
    assert len(store.photos)==len(store.events)==1
    event=store.events[0][0]
    assert set(event.data)=={'listing_id','revision'}
    assert 'photo' not in json.dumps(result)


@pytest.mark.asyncio
async def test_failed_photo_rolls_back_and_same_operation_can_recover(adapter):
    module,store=adapter
    issued=(await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,Provider())))['proof']
    body=module.Submission(expected_revision=1,challenge_id=issued['challenge_id'],code=issued['code'],photo_base64='invalid!',safe_photo=True,synthetic_photo=True)
    with pytest.raises(Exception) as caught:
        await module.command('submit',LISTING,body,request(store,Provider(),'submit-0001'))
    assert caught.value.code=='bad_photo'
    assert json.loads(store.proof)['state']=='issued'
    assert len(store.receipts)==1 and not store.photos and not store.events


@pytest.mark.asyncio
async def test_uncomposed_storage_is_unavailable_without_a_receipt(adapter):
    module,store=adapter
    store.storage_ready=False
    with pytest.raises(Exception) as caught:
        await module.command('issue',LISTING,module.Issue(expected_revision=0),request(store,Provider()))
    assert caught.value.code=='unavailable'
    assert not store.receipts and store.proof is None


def test_current_module_discovery_and_route_loading(adapter):
    from bt_runtime.modules import discover
    modules=discover(ROOT/'services/identity/modules')
    module=next(item for item in modules if item.id=='L01.private-seller')
    assert all(path.name.startswith('L01_') for path in module.migrations)
    router=module.load('routes.py:router')
    assert any(route.path.endswith('/possession/challenges') for route in router.routes)
