"""Exercise the published canonical engine and real proxy hook, not a second bid algorithm."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from service_app.kernel import transition
from conftest import BUYER, OTHER, SELLER, headers


def access(app,fixture,actor,key=None):
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    app.state.settings.auth_public_key=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now=datetime.now(timezone.utc)
    token=jwt.encode({'sub':str(actor),'sid':'sample-session','type':'access','iss':app.state.settings.auth_issuer,'aud':app.state.settings.auth_audience,'iat':now,'exp':now+timedelta(minutes=20)},private,algorithm='RS256')
    fixture.actors[token]=fixture.actors[str(actor)]
    return {**headers(actor,key),'Authorization':'Bearer '+token}


async def schedule(api,seconds):
    client,app,fixture,id=api
    now=datetime.now(timezone.utc)
    response=await client.patch(f'/v1/auctions/{id}/rules',headers=headers(SELLER,revision=2),json={'currency':'USD','opening_minor':400000,'reserve_minor':450000,'increment_bands':[{'from_minor':0,'step_minor':10000}],'starts_at':(now-timedelta(minutes=1)).isoformat(),'ends_at':(now+timedelta(seconds=seconds)).isoformat()})
    assert response.status_code==200,response.text
    return (await client.get(f'/v1/auctions/{id}/policy')).json()


@pytest.mark.parametrize('kind',['bids','maximum'])
async def test_late_manual_and_proxy_extend_once_and_replay_never_extends(api,kind):
    client,app,fixture,id=api
    before=await schedule(api,60)
    auth=access(app,fixture,BUYER,'same-accepted-bid') if kind=='maximum' else headers(BUYER,'same-accepted-bid')
    body={'amount_minor':600000 if kind=='maximum' else 400000,'expected_revision':before['revision'],'fee_quote_id':str(uuid4())}
    result=await client.post(f'/v1/auctions/{id}/{kind}',headers=auth,json=body)
    assert result.status_code==200 and result.json()['status']=='succeeded',result.text
    same=await client.post(f'/v1/auctions/{id}/{kind}',headers=auth,json=body)
    assert same.json()==result.json()
    after=(await client.get(f'/v1/auctions/{id}/policy')).json()
    assert datetime.fromisoformat(after['current_ends_at'])==datetime.fromisoformat(before['current_ends_at'])+timedelta(seconds=120)
    assert after['end_version']==before['end_version']+1
    assert after['reserve_met'] is False  # A private cap above reserve is not the public price.
    async with unit_of_work(app.state.pool) as tx:
        with pytest.raises(PublicError) as error:
            await transition(tx,id,expected_revision=before['revision'],expected_end_version=before['end_version'],from_mode='bidding',to_mode='closed_no_sale')
        assert error.value.code=='stale_revision'
        assert await tx.fetchval('SELECT count(*) FROM auction_bids WHERE auction_id=$1',id)==1
        envelopes=await tx.fetch("SELECT envelope FROM outbox WHERE envelope->>'type'='auction.bid-accepted.v1'")
        assert len(envelopes)==1 and after['current_ends_at'] in str(envelopes)


async def test_two_proxy_rows_share_one_atomic_end_version_update(api):
    client,app,fixture,id=api
    before=await schedule(api,130)
    maximum=await client.post(f'/v1/auctions/{id}/maximum',headers=access(app,fixture,BUYER),json={'amount_minor':600000,'expected_revision':before['revision'],'fee_quote_id':str(uuid4())})
    assert maximum.status_code==200 and maximum.json()['status']=='succeeded',maximum.text
    current=(await client.get(f'/v1/auctions/{id}/policy')).json()
    assert current['end_version']==before['end_version']
    remaining=(datetime.fromisoformat(current['current_ends_at'])-datetime.now(timezone.utc)).total_seconds()
    await asyncio.sleep(max(0,remaining-118))
    response=await client.post(f'/v1/auctions/{id}/bids',headers=headers(OTHER),json={'amount_minor':410000,'expected_revision':current['revision'],'fee_quote_id':str(uuid4())})
    assert response.status_code==200 and response.json()['status']=='succeeded',response.text
    after=(await client.get(f'/v1/auctions/{id}/policy')).json()
    assert after['end_version']==before['end_version']+1
    assert datetime.fromisoformat(after['current_ends_at'])==datetime.fromisoformat(before['current_ends_at'])+timedelta(seconds=120)
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids WHERE auction_id=$1',id)==3
        assert await tx.fetchval('SELECT current_minor FROM auction_lots WHERE id=$1',id)==420000
    history=(await client.get(f'/v1/auctions/{id}/history')).text
    assert '600000' not in history and after['reserve_met'] is False
