"""Deferred connected cases: real engine/proxy with the provider's canonical kernel."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from conftest import BUYER, OTHER, SELLER, headers

pytest.importorskip('service_app.kernel', reason='Connected canonical kernel is provider-owned')


def access(app, fixture, actor, key=None):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.settings.auth_public_key = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now = datetime.now(timezone.utc)
    token = jwt.encode({'sub': str(actor), 'sid': 'sample-session', 'type': 'access', 'iss': app.state.settings.auth_issuer,
        'aud': app.state.settings.auth_audience, 'iat': now, 'exp': now+timedelta(minutes=20)}, private, algorithm='RS256')
    fixture.actors[token] = fixture.actors[str(actor)]
    return {**headers(actor, key), 'Authorization': 'Bearer '+token}


async def schedule(api, seconds):
    client, app, fixture, auction = api
    now = datetime.now(timezone.utc)
    response = await client.patch(f'/v1/auctions/{auction}/rules', headers=headers(SELLER, revision=1), json={
        'currency': 'USD', 'opening_minor': 400000, 'reserve_minor': 450000,
        'increment_bands': [{'from_minor': 0, 'step_minor': 10000}],
        'starts_at': (now-timedelta(minutes=1)).isoformat(), 'ends_at': (now+timedelta(seconds=seconds)).isoformat()})
    assert response.status_code == 200, response.text
    return (await client.get(f'/v2/auctions/{auction}/policy')).json()


@pytest.mark.parametrize('kind', ['bids', 'maximum'])
@pytest.mark.parametrize('seconds', [120, 90])
async def test_manual_and_proxy_keep_fixed_end_and_replay(api, kind, seconds):
    client, app, fixture, auction = api
    before = await schedule(api, seconds)
    auth = access(app, fixture, BUYER, 'same') if kind == 'maximum' else headers(BUYER, 'same')
    body = {'amount_minor': 600000 if kind == 'maximum' else 400000, 'expected_revision': before['revision'], 'fee_quote_id': str(uuid4())}
    result = await client.post(f'/v1/auctions/{auction}/{kind}', headers=auth, json=body)
    assert result.status_code == 200 and result.json()['status'] == 'succeeded', result.text
    assert (await client.post(f'/v1/auctions/{auction}/{kind}', headers=auth, json=body)).json() == result.json()
    after = (await client.get(f'/v2/auctions/{auction}/policy')).json()
    assert after['current_ends_at'] == before['current_ends_at'] and after['end_version'] == before['end_version']


async def test_two_proxy_rows_never_change_the_scheduled_end(api):
    client, app, fixture, auction = api
    before = await schedule(api, 90)
    maximum = await client.post(f'/v1/auctions/{auction}/maximum', headers=access(app, fixture, BUYER), json={
        'amount_minor': 600000, 'expected_revision': before['revision'], 'fee_quote_id': str(uuid4())})
    assert maximum.status_code == 200 and maximum.json()['status'] == 'succeeded', maximum.text
    current = (await client.get(f'/v2/auctions/{auction}/policy')).json()
    response = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(OTHER), json={
        'amount_minor': 410000, 'expected_revision': current['revision'], 'fee_quote_id': str(uuid4())})
    assert response.status_code == 200 and response.json()['status'] == 'succeeded', response.text
    after = (await client.get(f'/v2/auctions/{auction}/policy')).json()
    assert after['end_version'] == before['end_version'] and after['current_ends_at'] == before['current_ends_at']
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids WHERE auction_id=$1', auction) == 3
    assert '600000' not in (await client.get(f'/v1/auctions/{auction}/history')).text
