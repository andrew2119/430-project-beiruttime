from datetime import datetime, timedelta, timezone
from uuid import uuid4
import asyncpg
import httpx
import pytest
from bt_contracts_core.errors import PublicError
from service_app.engine import AuctionEngine, time_denial
from service_app.main import create_app
from bt_runtime.app.settings import Settings
from pathlib import Path
from test_admission import bid, BUYER, OTHER, SELLER, headers, open_auction, rules


@pytest.mark.parametrize('seconds,code', [(-1,'not_started'),(0,None),(1,None),(3599,None),(3600,'auction_ended'),(3601,'auction_ended')])
def test_server_window_before_equal_after(seconds, code):
    start = datetime(2026,11,4,12,0,tzinfo=timezone.utc)
    assert time_denial({'starts_at': start, 'ends_at': start + timedelta(hours=1)},
        start + timedelta(seconds=seconds)) == code


async def test_restart_preserves_stored_acknowledgement(api, database_url):
    client, first_app, upstream = api
    auction = await open_auction(api)
    result = (await bid(api, auction, key='restart-operation')).json()
    restored = create_app(Settings(database_url=database_url, modules_path=Path('/app/modules')), upstream.dependencies())
    restored.state.pool = first_app.state.pool
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restored),base_url='http://test') as restarted:
        assert (await restarted.get('/v1/auction-operations/by-key/restart-operation', headers=headers(BUYER))).json() == result
        history = (await restarted.get(f'/v1/auctions/{auction}/history')).json()
        assert history['items'][0]['amount_minor'] == 400000
    await restored.state.auction.dependencies.close()


async def test_denial_is_not_resurrected_after_revision_changes(api):
    client, _, upstream = api
    auction = await open_auction(api)
    command = {'amount_minor': 399999, 'expected_revision': 1,
        'fee_quote_id': upstream.quote(auction, BUYER, 399999)}
    original = (await client.post(f'/v1/auctions/{auction}/bids', json=command, headers=headers(BUYER,'denied-once'))).json()
    await bid(api, auction, OTHER)
    replay = (await client.post(f'/v1/auctions/{auction}/bids', json=command, headers=headers(BUYER,'denied-once'))).json()
    assert original == replay and replay['code'] == 'bid_too_low'


async def test_database_guards_frozen_economics_and_monotonic_sequence(api):
    _, app, _ = api
    auction = await open_auction(api)
    await bid(api, auction)
    async with app.state.pool.acquire() as tx:
        for sql in ('UPDATE auction_lots SET opening_minor=opening_minor+1',
                    'UPDATE auction_lots SET ends_at=ends_at+interval \'1 hour\'',
                    'UPDATE auction_lots SET accepted_sequence=0',
                    'UPDATE auction_lots SET revision=1'):
            with pytest.raises(asyncpg.CheckViolationError):
                await tx.execute(sql)
    assert auction


async def test_invalid_schedule_does_not_acquire_sale_fence(api):
    client, _, upstream = api
    now = datetime.now(timezone.utc)
    result = await client.post('/v1/auctions', json=rules(
        starts_at=(now-timedelta(hours=2)).isoformat(),ends_at=(now-timedelta(hours=1)).isoformat()), headers=headers(SELLER))
    assert result.status_code == 409
    assert upstream.auction_id is None


async def test_cross_seller_rules_and_private_operation_access_denied(api):
    client, _, _ = api
    auction = await open_auction(api)
    body = rules()
    body.pop('listing_id')
    result = await client.patch(f'/v1/auctions/{auction}/rules',json=body,headers={**headers(OTHER),'If-Match':'1'})
    assert result.status_code == 403
    seller = (await client.get('/v1/seller/auctions',headers=headers(SELLER))).json()
    stranger = (await client.get('/v1/seller/auctions',headers=headers(OTHER))).json()
    assert len(seller['items']) == 1 and not stranger['items']
    assert seller['items'][0]['reserve_minor'] == 450000


async def test_orders_fence_lost_response_reconciles_same_source_without_second_commit(api):
    client, app, upstream = api
    command = rules()
    auth = headers(SELLER, 'lost-fence-response')
    upstream.drop_fence_response = True
    first = await client.post('/v1/auctions', json=command, headers=auth)
    assert first.status_code == 503 and upstream.commitment_acquired
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_lots') == 0
    upstream.drop_fence_response = False
    retry = await client.post('/v1/auctions', json=command, headers=auth)
    assert retry.status_code == 200 and retry.json()['status'] == 'succeeded'
    assert upstream.fence_posts == 1
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_lots') == 1


async def test_business_stock_permission_is_reselected_by_identity_and_cannot_mix_organizations(api):
    from bt_runtime.principal import OrganizationGrant
    client, app, upstream = api
    organization, unrelated = uuid4(), uuid4()
    actor = upstream.actors[str(SELLER)]
    actor.permissions = []
    actor.organizations = [organization, unrelated]
    actor.organization_grants = [OrganizationGrant(organization_id=organization,
        permissions=['identity.listings.publish'], roles=['dealer'])]
    upstream.listing_organization_id = organization
    # Another authorized staff member can schedule; canonical seller remains the listing's seller.
    upstream.listing_seller_id = OTHER
    command = rules()
    unselected = await client.post('/v1/auctions',json=command,headers=headers(SELLER))
    wrong = await client.post(f'/v1/auctions?organization_id={unrelated}',json=command,headers=headers(SELLER))
    assert unselected.status_code == wrong.status_code == 403
    response = await client.post(f'/v1/auctions?organization_id={organization}',json=command,headers=headers(SELLER))
    assert response.status_code == 200
    auction = response.json()['auction_id']
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT seller_id FROM auction_lots') == OTHER
    # Business membership blocks a personal self-bid even without a selected organization.
    upstream.actors[str(BUYER)].organizations = [organization]
    denied = await bid(api,auction)
    assert denied.json()['code'] == 'self_bid'
    scoped = await client.get(f'/v1/seller/auctions?organization_id={organization}',headers=headers(SELLER))
    assert len(scoped.json()['items']) == 1
    assert (await client.get(f'/v1/seller/auctions?organization_id={uuid4()}',headers=headers(SELLER))).status_code == 403


async def test_my_bids_is_owner_scoped_and_has_truthful_live_status(api):
    client, _, _ = api
    auction = await open_auction(api)
    await bid(api,auction)
    await bid(api,auction,OTHER,410000,2)
    mine = (await client.get('/v1/my-bids',headers=headers(BUYER))).json()
    assert mine['next_cursor'] is None and len(mine['items']) == 1
    row = mine['items'][0]
    assert row['buyer_id'] == str(BUYER) and row['auction_id'] == auction
    assert row['my_status'] == 'outbid' and row['status'] == 'live'
    assert row['current_price_minor'] == 410000 and 'maxima' not in row
    assert not (await client.get('/v1/my-bids',headers=headers(SELLER))).json()['items']


async def test_public_next_minimum_never_overflows_supported_minor_units(api):
    client, app, _ = api
    auction = await open_auction(api)
    result = await bid(api,auction,amount=9000000000000000)
    assert result.status_code == 200 and result.json()['code'] == 'bid_amount_limit'
    snapshot = (await client.get(f'/v1/auctions/{auction}')).json()
    assert snapshot['next_minimum_minor'] == 400000
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 0


async def test_opening_must_leave_room_for_a_representable_increment(api):
    client, _, upstream = api
    result = await client.post('/v1/auctions',json=rules(opening_minor=9000000000000000,reserve_minor=None),headers=headers(SELLER))
    assert result.status_code == 422 and upstream.auction_id is None


@pytest.mark.parametrize('defect',['too_low','foreign_maximum','lowered_foreign_maximum','duplicate_maximum','invalid_leader'])
def test_malformed_proxy_result_cannot_commit(defect):
    bidder, other = str(uuid4()), str(uuid4())
    state = {'current_minor':400000,'opening_minor':400000,'leader_id':other,'sequence':1,
        'increment_bands':[{'from_minor':0,'step_minor':10000}],
        'maxima':[{'bidder_id':other,'amount_minor':450000,'sequence':1}]}
    command = {'kind':'manual','bidder_id':bidder,'amount_minor':420000,'sequence':2}
    result = {'leader_id':other,'current_minor':430000,'maxima':[dict(state['maxima'][0])],
        'bids':[{'bidder_id':bidder,'amount_minor':420000,'automatic':False},
                {'bidder_id':other,'amount_minor':430000,'automatic':True}]}
    if defect == 'too_low':
        result['bids'][0]['amount_minor'] = 400001
    elif defect == 'foreign_maximum':
        result['maxima'][0]['amount_minor'] = 460000
    elif defect == 'lowered_foreign_maximum':
        result['maxima'][0]['amount_minor'] = 440000
    elif defect == 'duplicate_maximum':
        result['maxima'].append(dict(result['maxima'][0]))
    else:
        result['leader_id'] = str(uuid4())
    with pytest.raises(PublicError):
        AuctionEngine.validate_result(state,command,result)
