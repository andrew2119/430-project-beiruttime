import asyncio
import json
from uuid import UUID, uuid4
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from bt_runtime.app.settings import Settings
from service_app.main import create_app

ORIGIN={'Origin':'http://localhost:3000'}


@pytest.fixture
def keys(monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setenv('BT_AUTH_PRIVATE_KEY',private)
    monkeypatch.setenv('BT_LOCAL_HTTP','1')
    monkeypatch.setenv('BT_WEB_ORIGIN','http://localhost:3000')
    monkeypatch.delenv('BT_ALLOWED_WEB_ORIGINS',raising=False)
    monkeypatch.delenv('BT_EVENT_PRIVATE_KEY',raising=False)
    return private,public


@pytest_asyncio.fixture
async def environment(database_url,keys):
    app=create_app(Settings(database_url=database_url,service_name='identity',auth_public_key=keys[1]))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://localhost:3000',headers=ORIGIN) as client:
            yield app,client


async def register(client,email='sample@example.test',key='register-operation'):
    response=await client.post('/v1/accounts/register',headers={'Idempotency-Key':key},json={'email':email,'password':'A-long-sample-passphrase!','display_name':'Sample Buyer'})
    assert response.status_code==201,response.text
    return response.json()


def auth(session):
    return {'Authorization':'Bearer '+session['access_token']}


@pytest.mark.asyncio
async def test_register_login_restart_scope_and_outbox(environment,database_url,keys):
    app,client=environment
    first=await register(client)
    assert first['principal']['roles']==['buyer']
    assert first['principal']['permissions']==[]
    assert 'HttpOnly' in client.cookies.__str__() or client.cookies.get('bt_refresh')
    me=await client.get('/v1/accounts/me',headers=auth(first))
    assert me.json()['id']==first['account']['id']
    assert (await client.get('/internal/v1/principal',headers=auth(first))).json()==first['principal']
    assert (await client.post('/v1/accounts/login',json={'email':'sample@example.test','password':'incorrect'})).status_code==401
    login=await client.post('/v1/accounts/login',json={'email':'SAMPLE@example.test','password':'A-long-sample-passphrase!'})
    assert login.status_code==200
    async with app.state.pool.acquire() as tx:
        password=await tx.fetchval('SELECT password_hash FROM identity_accounts')
        assert password.startswith('scrypt$') and 'passphrase' not in password
        events=await tx.fetch('SELECT envelope FROM outbox')
        assert len(events)==1 and 'password' not in events[0]['envelope']
    restarted=create_app(Settings(database_url=database_url,service_name='identity',auth_public_key=keys[1]))
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(transport=ASGITransport(app=restarted),base_url='http://localhost:3000') as other:
            assert (await other.get('/v1/accounts/me',headers=auth(first))).json()['id']==first['account']['id']
    assert (await client.post('/v1/accounts/register',headers={'Origin':'https://evil.test','Idempotency-Key':'bad-origin'},json={'email':'evil@example.test','password':'A-long-sample-passphrase!','display_name':'Sample'})).status_code==403


@pytest.mark.asyncio
async def test_registration_duplicate_and_forbidden_self_grant(environment):
    app,client=environment
    first,second=await asyncio.gather(register(client),register(client))
    assert first['account']['id']==second['account']['id']
    bad=await client.post('/v1/accounts/register',headers={'Idempotency-Key':'changed-operation'},json={'email':'grant@example.test','password':'A-long-sample-passphrase!','display_name':'Sample','role':'operator'})
    assert bad.status_code==422
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM identity_accounts')==1
        assert await tx.fetchval('SELECT count(*) FROM identity_access_grants')==0
        assert await tx.fetchval('SELECT count(*) FROM outbox')==1


@pytest.mark.asyncio
async def test_refresh_replay_logout_race_and_password_revocation(environment):
    app,client=environment
    first=await register(client)
    original=client.cookies.get('bt_refresh')
    refresh=await client.post('/v1/accounts/refresh')
    assert refresh.status_code==200 and client.cookies.get('bt_refresh')!=original
    replay=await client.post('/v1/accounts/refresh',headers={'Cookie':'bt_refresh='+original})
    assert replay.status_code==401
    assert (await client.get('/v1/accounts/me',headers=auth(first))).status_code==401
    login=(await client.post('/v1/accounts/login',json={'email':'sample@example.test','password':'A-long-sample-passphrase!'})).json()
    original=client.cookies.get('bt_refresh')
    results=await asyncio.gather(client.post('/v1/accounts/refresh',headers={'Cookie':'bt_refresh='+original}),client.post('/v1/accounts/logout',headers={'Cookie':'bt_refresh='+original}))
    assert results[1].status_code==200
    assert (await client.get('/v1/accounts/me',headers=auth(login))).status_code==401
    login=(await client.post('/v1/accounts/login',json={'email':'sample@example.test','password':'A-long-sample-passphrase!'})).json()
    changed=await client.post('/v1/accounts/password',headers=auth(login),json={'current_password':'A-long-sample-passphrase!','new_password':'A-different-long-password!'})
    assert changed.status_code==200
    assert (await client.get('/v1/accounts/me',headers=auth(login))).status_code==401
    assert (await client.post('/v1/accounts/refresh')).status_code==401


@pytest.mark.asyncio
async def test_reset_one_use_expiry_generic_and_suspension(environment,keys):
    app,client=environment
    first=await register(client)
    known=await client.post('/v1/accounts/recovery',json={'email':'sample@example.test'})
    unknown=await client.post('/v1/accounts/recovery',json={'email':'absent@example.test'})
    assert known.status_code==unknown.status_code==202 and known.json()==unknown.json()
    assert (await client.get('/internal/v1/accounts/demo-mail',headers=auth(first))).status_code==403
    async with app.state.pool.acquire() as tx:
        await tx.execute('''INSERT INTO identity_access_grants(id,subject_id,role,permissions)
            VALUES($1,$2,'operator',ARRAY['identity.demo-mail.read'])''',uuid4(),UUID(first['account']['id']))
    captured=await client.get('/internal/v1/accounts/demo-mail',headers=auth(first))
    assert captured.status_code==200 and len(captured.json()['messages'])==1
    token=captured.json()['messages'][0]['recovery_link'].split('#')[1]
    async with app.state.pool.acquire() as tx:
        assert not await tx.fetchval('SELECT EXISTS(SELECT 1 FROM identity_password_resets WHERE hash=$1)',token)
        assert token not in await tx.fetchval('SELECT ciphertext FROM identity_demo_mail')
    body={'token':token,'password':'A-recovered-long-password!'}
    raced=await asyncio.gather(client.post('/v1/accounts/reset',json=body),client.post('/v1/accounts/reset',json=body))
    assert sorted(response.status_code for response in raced)==[200,400]
    assert (await client.post('/v1/accounts/reset',json=body)).status_code==400
    assert (await client.get('/v1/accounts/me',headers=auth(first))).status_code==401
    again=(await client.post('/v1/accounts/login',json={'email':'sample@example.test','password':'A-recovered-long-password!'})).json()
    await client.post('/v1/accounts/recovery',json={'email':'sample@example.test'})
    latest=(await client.get('/internal/v1/accounts/demo-mail',headers=auth(again))).json()['messages'][0]['recovery_link'].split('#')[1]
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE identity_password_resets SET expires_at=now() WHERE consumed_at IS NULL")
    assert (await client.post('/v1/accounts/reset',json={'token':latest,'password':'Must-not-be-the-password!'})).status_code==400
    assert (await client.post('/v1/accounts/login',json={'email':'sample@example.test','password':'A-recovered-long-password!'})).status_code==200
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE identity_accounts SET status='suspended'")
    assert (await client.post('/v1/accounts/refresh')).status_code==401
    assert (await client.post('/v1/accounts/login',json={'email':'sample@example.test','password':'A-recovered-long-password!'})).status_code==401


@pytest.mark.asyncio
async def test_private_application_idempotency_stale_scope_and_bytes(environment):
    app,client=environment
    first=await register(client)
    payload={'identity_name':'DEMO Person','contact':'demo@example.test','payout_reference':'DEMO-RECIPIENT','identity_evidence':'DEMO: identity','possession_evidence':'DEMO: possession','expected_revision':0}
    headers={**auth(first),'Idempotency-Key':'private-operation'}
    result,duplicate=await asyncio.gather(client.post('/v1/private-seller/applications',headers=headers,json=payload),client.post('/v1/private-seller/applications',headers=headers,json=payload))
    assert result.status_code==duplicate.status_code==200,result.text
    assert result.json()==duplicate.json()
    case=result.json()['application']
    assert case['status']=='pending'
    assert (await client.post('/v1/private-seller/applications',headers=headers,json=payload)).json()==result.json()
    assert (await client.post('/v1/private-seller/applications',headers={**auth(first),'Idempotency-Key':'another-operation'},json=payload)).status_code==409
    assert (await client.post('/v1/private-seller/applications',headers=headers,json={**payload,'identity_name':'changed'})).status_code==409
    async with app.state.pool.acquire() as tx:
        evidence=await tx.fetchrow('SELECT * FROM identity_private_evidence LIMIT 1')
        assert await tx.fetchval('SELECT count(*) FROM identity_private_evidence')==2
    url=f"/v1/private-seller/applications/{case['id']}/evidence/{evidence['id']}"
    assert (await client.get(url,headers=auth(first))).text.startswith('DEMO:')
    second=await register(client,'other@example.test','register-other')
    assert (await client.get('/v1/private-seller/applications/me',headers=auth(second))).json()=={'application':None}
    assert (await client.get(url,headers=auth(second))).status_code==403
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM identity_security_audit WHERE action='private-seller.evidence' AND outcome='denied'")==1
        public=json.dumps([json.loads(r['envelope']) for r in await tx.fetch('SELECT envelope FROM outbox')])
        assert 'DEMO:' not in public and 'demo@example.test' not in public
    oversized={**payload,'identity_evidence':'DEMO:'+ 'x'*65536}
    assert (await client.post('/v1/private-seller/applications',headers={**auth(second),'Idempotency-Key':'oversized-operation'},json=oversized)).status_code==422
