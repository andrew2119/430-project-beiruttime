"""Two isolated domain databases, actual HTTP envelopes and the actual SQL outbox relay."""
from pathlib import Path
import httpx
from bt_bulkheads import DependencyClient
from bt_events import OutboxRelay
from bt_runtime import testing
from bt_runtime.app.db import create_pool
from bt_runtime.app.settings import Settings
from service_app.main import create_app as auction_app
from test_admission import BUYER, OTHER, Upstreams, bid, headers, open_auction
from test_notices import auth


async def test_committed_bid_outbox_reaches_prior_bidders_owner_private_notice_api(notice_api, monkeypatch, request, tmp_path):
    notices, communications, private = notice_api
    database = testing.database_access.__wrapped__(request, tmp_path)
    with monkeypatch.context() as scoped:
        scoped.setenv('BT_MODULES_PATH', '/app/auction-modules')
        access = await database.__anext__()
    upstream = Upstreams()
    application = auction_app(Settings(database_url=access.runtime_url, modules_path=Path('/app/auction-modules')),
        upstream.dependencies())
    application.state.pool = await create_pool(access.runtime_url)
    for dependency in communications.state.bid_notice_clients.values():
        await dependency.aclose()
    communications.state.bid_notice_clients = {
        'identity': DependencyClient('identity', 'http://identity', transport=httpx.MockTransport(upstream.handle)),
        'auction': DependencyClient('auction', 'http://auction', transport=httpx.ASGITransport(app=application))}
    delivery = DependencyClient('communications', 'http://communications',
        transport=httpx.ASGITransport(app=communications))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url='http://auction') as client:
            api = client, application, upstream
            auction = await open_auction(api)
            assert (await bid(api,auction)).json()['status'] == 'succeeded'
            assert (await bid(api,auction,OTHER,410000,2)).json()['status'] == 'succeeded'
            relay = OutboxRelay(application.state.pool, {'communications':delivery}, headers=lambda _:auth(private))
            assert await relay.tick() == 2
            assert await relay.tick() == 0
            result = await notices.get('/v1/bid-notices',headers=headers(BUYER))
            assert result.status_code == 200
            items = result.json()['items']
            assert sorted(notice['kind'] for notice in items) == ['bid_accepted','outbid']
            outbid = next(notice for notice in items if notice['kind']=='outbid')
            assert outbid['current_minor'] == 410000
            opened = (await notices.get('/v1/bid-notices/'+outbid['id'],headers=headers(BUYER))).json()
            assert opened['current']['current_minor'] == 410000 and opened['requires_new_fee_preview']
            assert (await notices.get('/v1/bid-notices/'+outbid['id'],headers=headers(OTHER))).status_code == 404
            async with application.state.pool.acquire() as tx:
                assert await tx.fetchval("SELECT count(*) FROM outbox WHERE destination='communications' AND delivered_at IS NOT NULL") == 2
                # A relay cannot steal or back off a neighboring destination's durable intent.
                assert await tx.fetchval("SELECT attempts FROM outbox WHERE destination='catalog'") == 0
                envelope = await tx.fetchval("SELECT envelope FROM outbox WHERE destination='communications' ORDER BY id DESC LIMIT 1")
            # Replaying after successful delivery leaves exactly one outbid transition.
            replay = await delivery.request('POST','/internal/v1/events',content=envelope,
                headers={**auth(private),'Content-Type':'application/json'})
            assert replay.json()['accepted'] is False
            again = (await notices.get('/v1/bid-notices',headers=headers(BUYER))).json()
            assert len(again['items']) == 2
    finally:
        await delivery.aclose()
        await application.state.auction.dependencies.close()
        await application.state.pool.close()
        await database.aclose()
