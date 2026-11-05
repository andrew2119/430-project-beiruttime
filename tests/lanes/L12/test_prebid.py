import asyncio
from uuid import uuid4
import pytest
from bt_runtime.modules import discover
from pathlib import Path
from conftest import BUYER, OTHER, SELLER, headers


def tick(app):
    root=Path('/app/modules')
    module=next(m for m in discover(root) if m.id=='L12.prebid-buy-now')
    return module.load('workers.py:tick')(app)


async def purchase(api,key='purchase'):
    client,app,fixture,id=api
    return await client.post(f'/v1/auctions/{id}/prebid-buy-now',headers=headers(key=key),json={'expected_revision':2,'quote_id':fixture.quote(id,2)})


async def test_missing_kernel_never_dispatches_a_prebid(api,monkeypatch):
    import sys
    client,app,fixture,id=api
    monkeypatch.setitem(sys.modules,'service_app.kernel',None)
    result=await client.post(f'/v1/auctions/{id}/prebid-buy-now',headers=headers(),json={'expected_revision':2,'quote_id':str(uuid4())})
    assert result.status_code==503 and fixture.posts==0


async def test_prebid_one_allocation_private_operation_and_safe_events(api):
    client,app,fixture,id=api
    quote=fixture.quote(id,2)
    body={'expected_revision':2,'quote_id':quote}
    first=await client.post(f'/v1/auctions/{id}/prebid-buy-now',headers=headers(key='same'),json=body)
    assert first.status_code==200,first.text
    assert first.json()['status']=='succeeded'
    same=await client.post(f'/v1/auctions/{id}/prebid-buy-now',headers=headers(key='same'),json=body)
    assert same.json()==first.json() and fixture.posts==1
    assert (await client.get('/v1/prebid-operations/same',headers=headers(OTHER))).status_code==404
    assert (await client.get('/v1/prebid-operations/same',headers=headers())).json()==first.json()
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT mode FROM auction_lots WHERE id=$1',id)=='prebid_reserved'
        events=str(await tx.fetch("SELECT envelope FROM outbox WHERE envelope->>'type'='auction.prebid-resolved.v1'"))
        assert str(BUYER) not in events and quote not in events


async def test_lost_response_persists_pending_then_recovers_durable_intent(api):
    client,app,fixture,id=api
    fixture.lose_response=True
    response=await purchase(api)
    assert response.status_code==200,response.text
    assert response.json()['status']=='pending'
    assert fixture.posts==1
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT mode FROM auction_lots WHERE id=$1',id)=='prebid_pending'
        await tx.execute("UPDATE auction_prebid_operations SET available_at=clock_timestamp()")
    # New worker entrypoint/claim reconciles remote canonical operation, never another reserve.
    fixture.lose_response=False
    await tick(app)
    recovered=await client.get('/v1/prebid-operations/purchase',headers=headers())
    assert recovered.json()['status']=='succeeded' and fixture.posts==1


@pytest.mark.parametrize('override',[{'total_minor':515001},{'currency':'LBP'},{'buyer_id':str(OTHER)},{'quote_id':str(uuid4())}])
async def test_mismatched_remote_acknowledgement_stays_pending(api,override):
    client,app,fixture,id=api
    fixture.lose_response=True
    assert (await purchase(api)).json()['status']=='pending'
    next(iter(fixture.remote.values()))['order'].update(override)
    async with app.state.pool.acquire() as tx:
        await tx.execute('UPDATE auction_prebid_operations SET available_at=clock_timestamp()')
    await tick(app)
    result=await client.get('/v1/prebid-operations/purchase',headers=headers())
    assert result.json()['status']=='pending' and fixture.posts==1
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT mode FROM auction_lots WHERE id=$1',id)=='prebid_pending'


async def test_known_denial_does_not_speculatively_unfence(api):
    client,app,fixture,id=api
    fixture.deny=True
    response=await purchase(api)
    assert response.json()['status']=='denied'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT mode FROM auction_lots WHERE id=$1',id)=='prebid_pending'


async def test_first_bid_and_prebid_race_have_one_mode_winner(api):
    client,app,fixture,id=api
    responses=await asyncio.gather(purchase(api),client.post(f'/v1/auctions/{id}/bids',headers=headers(OTHER),json={'amount_minor':400000,'expected_revision':2,'fee_quote_id':str(uuid4())}))
    assert sum(r.status_code==200 and r.json().get('status')=='succeeded' for r in responses)==1
    async with app.state.pool.acquire() as tx:
        lot=await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1',id)
        assert (lot['accepted_sequence']>0 and lot['mode']=='bidding') or (lot['accepted_sequence']==0 and lot['mode']=='prebid_reserved')


@pytest.mark.parametrize('override',[{'owner_id':str(OTHER)},{'subject_revision':1},{'price_minor':499999},{'reviewed_at':None},{'purpose':'bid'}])
async def test_wrong_or_stale_quote_does_not_freeze(api,override):
    client,app,fixture,id=api
    response=await client.post(f'/v1/auctions/{id}/prebid-buy-now',headers=headers(),json={'expected_revision':2,'quote_id':fixture.quote(id,2,**override)})
    assert response.status_code==409,response.text
    assert fixture.posts==0
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT mode FROM auction_lots WHERE id=$1',id)=='bidding'


async def test_committed_physical_watch_denies_before_local_freeze(api):
    client,app,fixture,id=api
    fixture.auction_committed=True
    response=await purchase(api)
    assert response.status_code==409 and fixture.posts==0
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT mode FROM auction_lots WHERE id=$1',id)=='bidding'
        assert await tx.fetchval('SELECT count(*) FROM auction_prebid_operations')==0


async def test_canonical_buy_now_price_cannot_change_while_pending(api):
    import asyncpg
    client,app,fixture,id=api
    fixture.lose_response=True
    assert (await purchase(api)).json()['status']=='pending'
    async with app.state.pool.acquire() as tx:
        with pytest.raises(asyncpg.CheckViolationError):
            await tx.execute('UPDATE auction_lots SET buy_now_minor=buy_now_minor+1 WHERE id=$1',id)
        assert await tx.fetchval('SELECT buy_now_minor FROM auction_lots WHERE id=$1',id)==500000


async def test_self_purchase_denied(api):
    client,app,fixture,id=api
    quote=fixture.quote(id,2,owner_id=str(SELLER))
    response=await client.post(f'/v1/auctions/{id}/prebid-buy-now',headers=headers(SELLER),json={'expected_revision':2,'quote_id':quote})
    assert response.status_code==403,response.text
    assert fixture.posts==0
