import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient, MockTransport, Response
from bt_bulkheads import DependencyClient
from bt_contracts_core.models import EventEnvelope
from bt_runtime.app.settings import Settings
from service_app.main import create_app


@pytest.fixture
def keys(monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.delenv('BT_EVENT_PRIVATE_KEY',raising=False)
    return private,public


@pytest_asyncio.fixture
async def environment(database_url,keys):
    buyer,brand,request_id,session=uuid4(),uuid4(),uuid4(),uuid4()
    now=datetime.now(timezone.utc)
    def token(subject=buyer,session_id=session,kind='access',aud='beirut-time'):
        return jwt.encode({'sub':str(subject),'sid':str(session_id),'iss':'beirut-time-identity','aud':aud,'type':kind,'iat':now,'exp':now+timedelta(minutes=5)},keys[0],algorithm='RS256')
    state={'buyer':buyer,'brand':brand,'request_id':request_id,'revision':1,'identity_down':False,'catalog_down':False,'brand_down':False,'brand_state':'active','permissions':[],'token':token}
    app=create_app(Settings(database_url=database_url,service_name='eligibility',auth_public_key=keys[1],service_auth_public_key=keys[1]))
    async with app.router.lifespan_context(app):
        await app.state.identity.aclose();await app.state.catalog.aclose()
        def identity(incoming):
            if state['identity_down']:return Response(503)
            if incoming.url.path.startswith('/v1/businesses/'):
                if state['brand_down']:return Response(503)
                return Response(200,json={'id':str(brand),'public_name':'Sample Brand','kind':'brand','capabilities':['customization'],'state':state['brand_state'],'revision':1,'sample':True,'platform_onboarded':True,'authenticated_business':True,'independent_watch_authentication_required':False})
            claims=jwt.decode(incoming.headers['authorization'].split(' ',1)[1],keys[1],algorithms=['RS256'],audience='beirut-time')
            return Response(200,json={'actor':{'subject_id':claims['sub'],'session_id':claims['sid'],'organization_id':None},'roles':['buyer'],'permissions':state['permissions'],'organizations':[],'organization_grants':[]})
        def catalog(incoming):
            assert incoming.url.path==f'/v1/request-drafts/{request_id}'
            if state['catalog_down']:return Response(503)
            claims=jwt.decode(incoming.headers['authorization'].split(' ',1)[1],keys[1],algorithms=['RS256'],audience='beirut-time')
            if claims['sub']!=str(state['buyer']):return Response(403)
            return Response(200,json={'id':str(request_id),'brand_id':str(brand),'kind':'customization','revision':state['revision'],'status':'draft','watch_context':'undecided','watch_reference':'','scope_intent':'','notes':'private neutral intent','options':{},'approved':False,'payment_authority':False})
        app.state.identity=DependencyClient('identity','http://identity',transport=MockTransport(identity))
        app.state.catalog=DependencyClient('catalog','http://catalog',transport=MockTransport(catalog))
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer '+token()}) as client:
            yield app,client,state


def payload(state,**changes):
    return {'request_id':str(state['request_id']),'brand_id':str(state['brand']),'request_revision':1,'purpose':'brand-request-identity','policy_version':'demo-identity-v1','decision':'agree','evidence':'DEMO: synthetic identity',**changes}


@pytest.mark.asyncio
async def test_explicit_private_consent_scope_idempotency_restart(environment,database_url,keys):
    app,client,state=environment
    headers={'Idempotency-Key':'consent-operation'}
    response,duplicate=await asyncio.gather(client.post('/v1/consents',headers=headers,json=payload(state)),client.post('/v1/consents',headers=headers,json=payload(state)))
    assert response.status_code==duplicate.status_code==200,response.text
    assert response.json()==duplicate.json()
    record=response.json()['consent']
    assert record['status']=='active' and response.json()['effective_grant'] is False
    assert 'evidence' not in json.dumps(record)
    assert (await client.post('/v1/consents',headers=headers,json=payload(state))).json()==response.json()
    assert (await client.post('/v1/consents',headers=headers,json=payload(state,decision='refuse',evidence=None))).status_code==409
    assert (await client.get('/v1/consents')).json()['consents'][0]['id']==record['id']
    other=uuid4()
    different={'Authorization':'Bearer '+state['token'](other)}
    assert (await client.get('/v1/consents',headers=different)).json()=={'consents':[]}
    assert (await client.post('/v1/consents',headers={**different,'Idempotency-Key':'cross-owner-request'},json=payload(state))).status_code==403
    async with app.state.pool.acquire() as tx:
        proof=await tx.fetchrow('SELECT * FROM eligibility_consent_evidence')
        assert await tx.fetchval('SELECT count(*) FROM eligibility_consents')==1
        assert 'DEMO:' not in await tx.fetchval('SELECT envelope FROM outbox LIMIT 1')
    assert (await client.get(f"/v1/consents/{record['id']}/evidence/{proof['id']}",headers=different)).status_code==403
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM eligibility_consent_audit WHERE outcome='denied'")==1
    restarted=create_app(Settings(database_url=database_url,service_name='eligibility',auth_public_key=keys[1]))
    async with restarted.router.lifespan_context(restarted):
        async with restarted.state.pool.acquire() as tx:
            assert await tx.fetchval('SELECT status FROM eligibility_consents')=='active'


@pytest.mark.asyncio
async def test_refusal_and_unavailable_never_store_evidence(environment):
    app,client,state=environment
    state['catalog_down']=True
    assert (await client.post('/v1/consents',headers={'Idempotency-Key':'catalog-unavailable'},json=payload(state))).status_code==503
    state['catalog_down']=False;state['identity_down']=True
    assert (await client.post('/v1/consents',headers={'Idempotency-Key':'identity-unavailable'},json=payload(state))).status_code==503
    state['identity_down']=False;state['brand_down']=True
    assert (await client.post('/v1/consents',headers={'Idempotency-Key':'brand-unavailable'},json=payload(state))).status_code==503
    state['brand_down']=False;state['brand_state']='revoked'
    assert (await client.post('/v1/consents',headers={'Idempotency-Key':'brand-revoked'},json=payload(state))).status_code==409
    state['brand_state']='active'
    bad=await client.post('/v1/consents',headers={'Idempotency-Key':'wrong-buyer-context'},json=payload(state,brand_id=str(uuid4())))
    assert bad.status_code==409
    refusal=await client.post('/v1/consents',headers={'Idempotency-Key':'refusal-operation'},json=payload(state,decision='refuse',evidence=None))
    assert refusal.status_code==200 and refusal.json()['consent']['status']=='refused'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM eligibility_consent_evidence')==0
        assert await tx.fetchval('SELECT count(*) FROM eligibility_consents')==1
    assert (await client.post('/v1/consents',headers={'Idempotency-Key':'no-policy-operation'},json=payload(state,policy_version='unknown-v2'))).status_code==422


@pytest.mark.asyncio
async def test_withdrawal_acknowledgements_service_auth_stale_and_duplicate(environment,keys):
    app,client,state=environment
    record=(await client.post('/v1/consents',headers={'Idempotency-Key':'consent-operation'},json=payload(state))).json()['consent']
    identifier=record['id']
    withdrawal=await client.post(f'/v1/consents/{identifier}/withdraw',headers={'Idempotency-Key':'withdraw-operation'},json={'expected_revision':1})
    assert withdrawal.status_code==200 and withdrawal.json()['consent']['status']=='withdrawal_pending'
    assert (await client.post(f'/v1/consents/{identifier}/withdraw',headers={'Idempotency-Key':'withdraw-operation'},json={'expected_revision':1})).json()==withdrawal.json()
    assert (await client.post(f'/v1/consents/{identifier}/withdraw',headers={'Idempotency-Key':'stale-withdrawal'},json={'expected_revision':1})).status_code==409
    def event(source,revision=2):
        return EventEnvelope(type=source+'.consent-fenced.v1',source=source,subject=identifier,request_id='proof-fence',data={'consent_id':identifier,'revision':revision}).model_dump(mode='json')
    assert (await client.post('/internal/v1/events',json=event('catalog'))).status_code==401
    async def ack(source,revision=2,envelope=None):
        return await client.post('/internal/v1/events',headers={'Authorization':'Bearer '+state['token'](source,kind='service',aud='eligibility')},json=envelope or event(source,revision))
    assert (await ack('catalog',1)).status_code==409
    assert (await ack('catalog',2.5)).status_code==422
    mismatched=event('catalog');mismatched['subject']=str(uuid4())
    assert (await ack('catalog',envelope=mismatched)).status_code==409
    assert (await ack('catalog')).status_code==200
    assert (await client.get('/v1/consents')).json()['consents'][0]['status']=='withdrawal_pending'
    final=event('orders')
    assert (await ack('orders',envelope=final)).status_code==200
    assert (await ack('orders',envelope=final)).json()=={'accepted':False}
    assert (await client.get('/v1/consents')).json()['consents'][0]['status']=='withdrawn'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM eligibility_consent_fences')==2
        assert await tx.fetchval('SELECT count(*) FROM inbox')==2
        assert await tx.fetchval('SELECT count(*) FROM outbox')==3
