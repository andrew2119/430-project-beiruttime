import asyncio
import importlib.util
import sys
import types
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI
import httpx
import pytest

ROOT=Path(__file__).resolve().parents[4]
package=types.ModuleType('l19_signals')
package.__path__=[str(ROOT/'services/trust/modules/fraud-signals')]
sys.modules['l19_signals']=package
from l19_signals.core import Store
from l19_signals.adapter import create_router
spec=importlib.util.spec_from_file_location('l19_contract',ROOT/'packages/contracts-trust/fraud-signals/v1.py')
contract=importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
BODY=dict(schema_version='fraud-signals.v1',operation_id='operation-0001',subject_id='subject',watch_id='watch',organization_id='business',expected_revision=0,source_revision=1)

class Provider:
    def __init__(self):
        self.allowed=True
        self.timeout=False
        self.omit_parties=False

    @asynccontextmanager
    async def current(self,request,body):
        if self.timeout:
            await asyncio.sleep(2)
        now=datetime.now(timezone.utc)
        snapshot = {'context':dict(actor_id='reviewer',organization_id='business',subject_id='subject',watch_id='watch',
                             source_revision=1,record_revision=0,assigned=True,permitted=self.allowed,
                             seller_id='seller',parties=['seller','subject'],valid_until=now+timedelta(seconds=2)),
               'photos':[], 'bids':[]}
        if self.omit_parties:
            del snapshot['context']['parties']
        yield snapshot

@pytest.fixture
def client(tmp_path):
    app=FastAPI()
    app.include_router(create_router(contract.Scan,contract.Photo,contract.Bid))
    app.state.fraud_signal_store=Store(tmp_path/'signals.db')
    app.state.fraud_signal_provider=Provider()
    class Client:
        def request(self, method, path, **kwargs):
            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                    return await client.request(method,path,**kwargs)
            return asyncio.run(send())
        def get(self,path,**kwargs):
            return self.request('GET',path,**kwargs)
        def post(self,path,**kwargs):
            return self.request('POST',path,**kwargs)
    yield Client(),app.state
    app.state.fraud_signal_store.close()


def test_post_lookup_duplicate_revoked(client):
    client,state=client
    first=client.post('/v1/fraud-signals/scans',json=BODY)
    assert first.status_code==200
    assert client.post('/v1/fraud-signals/scans',json=BODY).json()==first.json()
    assert client.get('/v1/fraud-signals/operations/operation-0001').json()==first.json()
    assert client.get('/v1/fraud-signals').json()['total']==1
    state.fraud_signal_provider.allowed=False
    assert client.get('/v1/fraud-signals/operations/operation-0001').status_code==403
    assert client.get('/v1/fraud-signals').status_code==403
    assert client.post('/v1/fraud-signals/scans',json=BODY).status_code==403


def test_timeout_never_success_and_same_reference_recovers(client):
    client,state=client
    state.fraud_signal_provider.timeout=True
    assert client.post('/v1/fraud-signals/scans',json=BODY).status_code==503
    state.fraud_signal_provider.timeout=False
    assert client.get('/v1/fraud-signals').json()['total']==0
    assert client.post('/v1/fraud-signals/scans',json=BODY).status_code==200


def test_missing_provider_and_bounded_invalid_input(client):
    client,state=client
    assert client.post('/v1/fraud-signals/scans',content='x'*4097).status_code==413
    assert client.post('/v1/fraud-signals/scans',json={**BODY,'device':'value'}).status_code==422
    assert client.post('/v1/fraud-signals/scans',json={**BODY,'organization_id':'other'}).status_code==403
    assert client.get('/v1/fraud-signals?page_size=51').status_code==422
    state.fraud_signal_provider=None
    assert client.post('/v1/fraud-signals/scans',json=BODY).status_code==503


def test_incomplete_independence_returns_denied_for_all_routes(client):
    client, state = client
    assert client.post('/v1/fraud-signals/scans', json=BODY).status_code == 200
    state.fraud_signal_provider.omit_parties = True
    assert client.post('/v1/fraud-signals/scans', json=BODY).status_code == 403
    assert client.get('/v1/fraud-signals/operations/operation-0001').status_code == 403
    assert client.get('/v1/fraud-signals').status_code == 403
