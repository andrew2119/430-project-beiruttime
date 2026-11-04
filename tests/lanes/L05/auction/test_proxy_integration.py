"""Actual frozen L06 pure callback with the owning SQL admission transaction."""
from uuid import UUID
import time
import jwt
import pytest
from fastapi import Request
from bt_contracts.auction.core.models import BidCommand
from proxy_contract_fixture import calculate
from test_admission import BUYER, OTHER, SERVICE_PRIVATE, SERVICE_PUBLIC, bid, headers, open_auction


def install(api):
    client, app, upstream = api
    app.state.hooks['auction.proxy.v1'] = calculate
    @app.post('/test/maximum/{auction_id}')
    async def maximum(auction_id: UUID, command: BidCommand, request: Request):
        return await app.state.auction.submit(request, auction_id, command, kind='maximum')
    return client, app, upstream


async def maximum(api, auction, actor=BUYER, amount=450000, revision=1, key=None):
    client, _, upstream = api
    return await client.post(f'/test/maximum/{auction}', headers=headers(actor, key), json={
        'amount_minor': amount, 'expected_revision': revision,
        'fee_quote_id': upstream.quote(auction, actor, amount, subject_revision=revision)})


async def test_real_proxy_responds_inside_one_durable_bid_transaction(api):
    client, app, _ = install(api)
    auction = await open_auction(api)
    first = await maximum(api, auction)
    assert first.status_code == 200 and first.json()['current_minor'] == 400000
    response = await bid(api, auction, OTHER, 420000, 2)
    assert response.json()['current_minor'] == 430000 and response.json()['accepted_sequence'] == 3
    history = (await client.get(f'/v1/auctions/{auction}/history')).json()
    assert [row['amount_minor'] for row in history['items']] == [400000,420000,430000]
    assert [row['automatic'] for row in history['items']] == [True,False,True]
    assert '450000' not in str(history)
    async with app.state.pool.acquire() as tx:
        caps = await tx.fetch('SELECT * FROM auction_maxima ORDER BY amount_minor DESC')
        assert [(row['bidder_id'],row['amount_minor']) for row in caps] == [(BUYER,450000),(OTHER,420000)]
        assert '450000' not in str(await tx.fetch('SELECT envelope FROM outbox'))
        assert await tx.fetchval('SELECT count(*) FROM auction_operations') == 3


async def test_equal_maximum_favors_earlier_authoritative_sequence(api):
    _, app, _ = install(api)
    auction = await open_auction(api)
    await maximum(api, auction)
    response = await maximum(api, auction, OTHER,450000,2)
    assert response.status_code == 200 and response.json()['current_minor'] == 450000
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT leader_id FROM auction_lots') == BUYER
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 2


async def test_manual_tie_does_not_steal_earlier_ceiling_or_create_false_outbid(api):
    _, app, _ = install(api)
    auction = await open_auction(api)
    await maximum(api, auction)
    response = await bid(api, auction, OTHER,450000,2)
    assert response.status_code == 200 and response.json()['status'] == 'succeeded'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT leader_id FROM auction_lots') == BUYER
        data = await tx.fetchval("SELECT envelope->'data' FROM outbox WHERE envelope->>'type'='auction.bid-accepted.v1' ORDER BY id DESC LIMIT 1")
        assert str(BUYER) in data


async def test_automatic_response_never_exceeds_cap_even_at_partial_increment(api):
    _, app, _ = install(api)
    auction = await open_auction(api)
    await maximum(api, auction, amount=425000)
    response = await bid(api, auction, OTHER,420000,2)
    assert response.status_code == 200 and response.json()['current_minor'] == 425000
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT max(amount_minor) FROM auction_bids') == 425000


async def test_leading_private_raise_has_no_public_price_transition(api):
    client, app, _ = install(api)
    auction = await open_auction(api)
    await maximum(api, auction)
    response = await maximum(api, auction, amount=460000,revision=2)
    assert response.json()['status'] == 'succeeded' and response.json()['current_minor'] == 400000
    history = (await client.get(f'/v1/auctions/{auction}/history')).json()
    assert len(history['items']) == 1
    assert '460000' not in str(history)
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT amount_minor FROM auction_maxima WHERE bidder_id=$1',BUYER) == 460000


async def test_manual_history_remains_compatible_when_proxy_module_arrives(api):
    _, app, _ = api
    app.state.hooks.pop('auction.proxy.v1', None)
    auction = await open_auction(api)
    assert (await bid(api, auction)).json()['status'] == 'succeeded'
    _, app, _ = install(api)
    response = await maximum(api, auction, OTHER,450000,2)
    assert response.status_code == 200 and response.json()['current_minor'] == 410000
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT leader_id FROM auction_lots') == OTHER
        assert await tx.fetchval('SELECT count(*) FROM auction_maxima') == 2


async def test_active_private_ceiling_is_never_silently_ignored_if_hook_unavailable(api):
    _, app, _ = install(api)
    auction = await open_auction(api)
    await maximum(api, auction)
    del app.state.hooks['auction.proxy.v1']
    response = await bid(api, auction, OTHER,420000,2)
    assert response.status_code == 503
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 1


async def test_published_l06_route_and_module_registration_use_the_one_engine(api):
    client, app, upstream = api
    if not any(module.id == 'L06.proxy' for module in app.state.modules):
        pytest.skip('Install the published L06 module for this cross-module proof')
    app.state.settings.auth_public_key = SERVICE_PUBLIC
    now = int(time.time())
    token = jwt.encode({'sub': str(BUYER), 'sid': 'sample-session', 'type': 'access',
        'iss': 'beirut-time-identity', 'aud': 'beirut-time', 'iat': now, 'exp': now+60},
        SERVICE_PRIVATE, algorithm='RS256')
    upstream.actors[token] = upstream.actors[str(BUYER)]
    auction = await open_auction(api)
    body = {'amount_minor': 450000, 'expected_revision': 1,
        'fee_quote_id': upstream.quote(auction, BUYER, 450000)}
    response = await client.post(f'/v1/auctions/{auction}/maximum', headers=headers(token), json=body)
    assert response.status_code == 200 and response.json()['status'] == 'succeeded'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_lots') == 1
        assert await tx.fetchval('SELECT count(*) FROM auction_maxima') == 1
        assert await tx.fetchval('SELECT amount_minor FROM auction_maxima') == 450000
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 1


async def test_nonincreasing_maximum_is_stored_as_denied_not_an_outage(api):
    _, app, _ = install(api)
    auction = await open_auction(api)
    await maximum(api, auction)
    response = await maximum(api, auction, amount=450000,revision=2)
    assert response.status_code == 200 and response.json()['code'] == 'maximum_must_increase'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM auction_operations WHERE outcome->>'status'='denied'") == 1
