from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from bt_contracts.auction.core.models import AuctionTimingV1, AuctionTimingPageV1
from test_admission import open_auction


async def test_timing_read_has_canonical_ends_server_time_status_and_no_private_economics(api):
    client, _, _ = api
    auction = await open_auction(api)
    response = await client.get(f'/v1/auctions/{auction}/timing')
    assert response.status_code == 200
    snapshot = AuctionTimingV1.model_validate(response.json())
    assert snapshot.current_ends_at == snapshot.scheduled_ends_at
    assert snapshot.status == 'live' and snapshot.extension_policy == 'none.v1'
    assert snapshot.server_time.tzinfo is not None
    assert 'reserve' not in response.text and 'seller_id' not in response.text and 'maxima' not in response.text
    assert (await client.get(f'/v1/auctions/{uuid4()}/timing')).status_code == 404


async def test_ending_soon_order_and_cursor_are_owned_by_auction(api):
    client, _, upstream = api
    now = datetime.now(timezone.utc)
    later = await open_auction(api, ends_at=(now+timedelta(hours=2)).isoformat())
    upstream.listing_id, upstream.watch_id = uuid4(), uuid4()
    upstream.auction_id, upstream.commitment_acquired = None, False
    sooner = await open_auction(api, listing_id=str(upstream.listing_id), ends_at=(now+timedelta(hours=1)).isoformat())
    first = (await client.get('/v1/auction-timing?status=live&limit=1')).json()
    AuctionTimingPageV1.model_validate(first)
    assert [row['auction_id'] for row in first['items']] == [sooner]
    assert first['next_cursor'] == sooner
    second = (await client.get('/v1/auction-timing?status=live&limit=1&cursor='+first['next_cursor'])).json()
    assert [row['auction_id'] for row in second['items']] == [later]
    assert second['next_cursor'] is None


async def test_batch_missing_does_not_confuse_status_filter_with_unknown_lot(api):
    client, app, upstream = api
    auction = await open_auction(api)
    unknown = uuid4()
    query = f'listing_ids={upstream.listing_id},{unknown}&status=scheduled'
    result = (await client.get('/v1/auction-timing?'+query)).json()
    assert not result['items'] and result['missing_listing_ids'] == [str(unknown)]
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE auction_lots SET starts_at=now()+interval '30 minutes' WHERE id=$1", UUID(auction))
    scheduled = (await client.get('/v1/auction-timing?'+query)).json()
    assert scheduled['items'][0]['status'] == 'scheduled'
    assert scheduled['items'][0]['server_time'] == scheduled['server_time']
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE auction_lots SET starts_at=now()-interval '2 hours',ends_at=now()-interval '1 hour'")
    ended = (await client.get('/v1/auction-timing?status=ended')).json()
    assert ended['items'][0]['status'] == 'ended'
    assert not (await client.get('/v1/auction-timing')).json()['items']


@pytest.mark.parametrize('query',['listing_ids=not-a-uuid','limit=101','status=paid','listing_ids='+','.join(str(uuid4()) for _ in range(101))])
async def test_timing_reads_are_bounded_and_typed(api, query):
    client, _, _ = api
    assert (await client.get('/v1/auction-timing?'+query)).status_code == 422
