from fastapi import Request,HTTPException
import pytest
from bt_runtime.app.db import unit_of_work
from service_app.identity import consume_reauthentication
from test_accounts import register,auth,environment as environment,keys as keys


@pytest.mark.asyncio
async def test_configured_origins_are_exact_and_fail_closed(environment,monkeypatch):
    _,client=environment
    monkeypatch.setenv('BT_ALLOWED_WEB_ORIGINS','http://localhost:3000,http://localhost:3077')
    await register(client)
    body={'email':'sample@example.test','password':'A-long-sample-passphrase!'}
    assert (await client.post('/v1/accounts/login',headers={'Origin':'http://localhost:3077'},json=body)).status_code==200
    assert (await client.post('/v1/accounts/login',headers={'Origin':'http://localhost:30770'},json=body)).status_code==403
    assert (await client.post('/v1/accounts/login',headers={'Origin':'null'},json=body)).status_code==403
    monkeypatch.setenv('BT_ALLOWED_WEB_ORIGINS','http://localhost:*')
    assert (await client.post('/v1/accounts/login',headers={'Origin':'http://localhost:3077'},json=body)).status_code==503


@pytest.mark.asyncio
async def test_contact_proof_is_one_use_and_bound_to_recipient_session_and_actor(environment):
    app,client=environment
    first=await register(client)
    @app.post('/test/consume-contact-proof')
    async def consume(body:dict,request:Request):
        async with unit_of_work(app.state.pool) as tx:
            await consume_reauthentication(tx,request,body['proof'],purpose='contact-change',binding=body['binding'])
            if body.get('fail'):
                raise HTTPException(409)
        return {'accepted':True}
    body={'password':'A-long-sample-passphrase!','purpose':'contact-change','binding':'email:new@example.test'}
    issued=await client.post('/v1/accounts/reauthenticate',headers=auth(first),json=body)
    assert issued.status_code==200
    proof=issued.json()['proof']
    async with app.state.pool.acquire() as tx:
        assert not await tx.fetchval('SELECT EXISTS(SELECT 1 FROM identity_reauth_proofs WHERE hash=$1)',proof)
    command={'proof':proof,'binding':body['binding']}
    other=await register(client,'other@example.test','register-other')
    assert (await client.post('/test/consume-contact-proof',headers=auth(other),json=command)).status_code==403
    assert (await client.post('/test/consume-contact-proof',headers=auth(first),json={**command,'binding':'email:other@example.test'})).status_code==403
    second=(await client.post('/v1/accounts/login',json={'email':'sample@example.test','password':'A-long-sample-passphrase!'})).json()
    assert (await client.post('/test/consume-contact-proof',headers=auth(second),json=command)).status_code==403
    assert (await client.post('/test/consume-contact-proof',headers=auth(first),json={**command,'fail':True})).status_code==409
    assert (await client.post('/test/consume-contact-proof',headers=auth(first),json=command)).status_code==200
    assert (await client.post('/test/consume-contact-proof',headers=auth(first),json=command)).status_code==403
    fresh=(await client.post('/v1/accounts/reauthenticate',headers=auth(first),json=body)).json()['proof']
    async with app.state.pool.acquire() as tx:
        await tx.execute('UPDATE identity_reauth_proofs SET expires_at=now() WHERE consumed_at IS NULL')
    assert (await client.post('/test/consume-contact-proof',headers=auth(first),json={**command,'proof':fresh})).status_code==403
