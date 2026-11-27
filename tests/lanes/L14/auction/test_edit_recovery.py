"""Real Auction DB, explicit Orders resolution contract peers; no live proof."""
import asyncio
import importlib
from contextvars import ContextVar
from datetime import datetime, timedelta
from uuid import uuid4
import asyncpg
import pytest
from test_kernel import api as api, open_lot, edit_body, machine, headers, BUYER

BASE = '/internal/v3/listing-edits'


def recovery(app):
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == BASE + '/{operation_id}/reconcile')
    return importlib.import_module(endpoint.__module__)


def worker(app):
    return importlib.import_module(recovery(app).__name__.rsplit('.', 1)[0] + '.workers')


async def prepared(api, *, lot=True):
    app, client, peers = api
    auction = await open_lot(api) if lot else None
    body, facts = edit_body(peers)
    body.update(orders_operation_key='edit:' + body['operation_id'], orders_expected_revision=peers.watch_revision, lease_seconds=30)
    response = await client.post(BASE + '/prepare', json=body, headers=machine(peers))
    assert response.status_code == 200, response.text
    return auction, body, facts, response.json()


def proof(body, **changes):
    return {'id': str(uuid4()), 'operation_key': body.get('orders_operation_key', body['operation_id']),
        'producer': 'catalog', 'kind': 'edit', 'source_id': body['operation_id'],
        'watch_id': body['watch_id'], 'listing_id': body['listing_id'], 'listing_revision': body['listing_revision'],
        'expected_revision': body.get('orders_expected_revision', 2), 'status': 'denied', **changes}


async def advance_clock(app, prepared_result, monkeypatch, seconds=0):
    now = datetime.fromisoformat(prepared_result['expires_at']) + timedelta(seconds=seconds)
    async def clock(tx):
        return now
    monkeypatch.setattr(recovery(app), 'server_now', clock)


@pytest.mark.asyncio
async def test_expiry_is_local_only_before_dispatch_and_terminal_abort_replays(api, monkeypatch):
    app, client, peers = api
    auction, body, _, original = await prepared(api)
    path = BASE + '/' + body['operation_id']
    await advance_clock(app, original, monkeypatch, -.000001)
    live = await client.post(path + '/abort', headers=machine(peers))
    assert live.json()['status'] == 'pending' and live.json()['code'] == 'prepare_lease_active'
    await advance_clock(app, original, monkeypatch)
    aborted = await client.post(path + '/reconcile', headers=machine(peers))
    assert aborted.json()['phase'] == 'aborted' and aborted.json()['code'] == 'prepare_expired'
    assert (await client.post(path + '/abort', headers=machine(peers))).json() == aborted.json()
    assert (await client.post(path + '/dispatch', headers=machine(peers))).json() == aborted.json()
    assert (await client.get(path, headers=machine(peers))).json() == aborted.json()
    assert (await client.post(BASE + '/prepare', json=body, headers=machine(peers))).json() == original
    assert (await client.post(path + '/commit', json={'listing_revision': 2}, headers=machine(peers))).status_code == 409
    assert (await client.post(BASE + '/prepare', json={**body, 'orders_operation_key': 'different-key'}, headers=machine(peers))).status_code == 409
    async with app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction)
        assert lot['mode'] == 'bidding' and lot['revision'] == 3 and lot['listing_revision'] == 1
        assert lot['end_version'] == 1
        assert await tx.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='auction.listing-edit-aborted.v3'") == 1
        with pytest.raises(asyncpg.CheckViolationError):
            await tx.execute("UPDATE auction_listing_edits SET state='prepared',aborted_at=NULL,abort_result=NULL")
    # Expiry does not send a physical command or a bid. Fresh current bid still
    # goes through normal Orders first-bid commitment, never a local shortcut.
    assert len(peers.intents) == 1
    response = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(BUYER), json={
        'amount_minor': 400000, 'expected_revision': 3, 'fee_quote_id': peers.quote(auction, BUYER, 400000, 3)})
    assert response.status_code == 200 and response.json()['status'] == 'succeeded', response.text


@pytest.mark.asyncio
async def test_dispatched_hold_never_expires_or_trusts_unknown_mismatched_denial(api, monkeypatch):
    app, client, peers = api
    auction, body, _, original = await prepared(api)
    path, h = BASE + '/' + body['operation_id'], machine(peers)
    dispatched = await client.post(path + '/dispatch', headers=h)
    assert dispatched.json()['phase'] == 'dispatched'
    await advance_clock(app, original, monkeypatch, 10000)
    assert (await client.post(path + '/dispatch', headers=h)).json() == dispatched.json()
    assert (await client.post(path + '/abort', headers=h)).json()['status'] == 'pending'  # 404 is not denial.
    peers.orders_resolution_unavailable = True
    assert (await client.post(path + '/abort', headers=h)).json()['status'] == 'pending'
    peers.orders_resolution_unavailable = False
    key = body['orders_operation_key']
    for changes in [{'status': 'succeeded'}, {'producer': 'auction'}, {'kind': 'withdraw'},
                    {'source_id': str(uuid4())}, {'watch_id': str(uuid4())}, {'listing_id': str(uuid4())},
                    {'listing_revision': 2}, {'expected_revision': 100}, {'operation_key': 'other'}, {'expected_revision': True}]:
        peers.edit_resolutions[key] = proof(body, **changes)
        assert (await client.post(path + '/abort', headers=h)).json()['status'] == 'pending', changes
    peers.edit_resolutions[key] = proof(body)
    peers.watch_status = 'reserved'
    assert (await client.post(path + '/abort', headers=h)).json()['status'] == 'pending'
    peers.watch_status = 'fenced'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT mode FROM auction_lots WHERE id=$1', auction) == 'listing_edit_pending'
    aborted = await client.post(path + '/abort', headers=h)
    assert aborted.json()['phase'] == 'aborted' and aborted.json()['code'] == 'orders_denied'
    assert (await client.post(path + '/reconcile', headers=h)).json() == aborted.json()
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT revision FROM auction_lots WHERE id=$1', auction) == 3
    assert len(peers.intents) == 1  # No new physical edit, allocation or fence fabricated.


@pytest.mark.asyncio
async def test_worker_finishes_committed_source_after_lost_refence_response(api):
    app, client, peers = api
    auction, body, facts, _ = await prepared(api)
    path, h = BASE + '/' + body['operation_id'], machine(peers)
    assert (await client.post(path + '/dispatch', headers=h)).json()['phase'] == 'dispatched'
    peers.listing_revision = peers.watch_listing_revision = 2
    peers.facts, peers.watch_revision, peers.watch_status, peers.auction = facts, 4, 'available', None
    peers.committed = True  # Actual Orders edit-complete retains the historical flag until refence.
    assert (await client.post(path + '/abort', headers=h)).json()['status'] == 'pending'
    peers.drop_open_reply = True
    unknown = await client.post(path + '/reconcile', headers=h)
    assert unknown.json()['status'] == 'pending'
    assert len(peers.intents) == 2  # Actual one refence succeeded, response was lost.
    assert await worker(app).tick(app) == 1
    committed = await client.get(path, headers=h)
    assert committed.json()['phase'] == 'committed'
    assert (await client.post(path + '/reconcile', headers=h)).json() == committed.json()
    assert await worker(app).tick(app) == 0
    async with app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction)
        assert row['mode'] == 'bidding' and row['revision'] == 3 and row['listing_revision'] == 2
    assert len(peers.intents) == 2


@pytest.mark.asyncio
async def test_worker_expires_only_never_dispatched_no_lot_hold(api, monkeypatch):
    app, client, peers = api
    _, body, _, original = await prepared(api, lot=False)
    await advance_clock(app, original, monkeypatch, 1)
    assert await worker(app).tick(app) == 1
    assert await worker(app).tick(app) == 0
    read = await client.get(BASE + '/' + body['operation_id'], headers=machine(peers))
    assert read.json()['phase'] == 'aborted' and read.json()['auction_id'] is None
    assert not peers.intents
    async with app.state.pool.acquire() as tx:
        assert not await tx.fetchval("SELECT EXISTS(SELECT 1 FROM auction_listing_edits WHERE state='prepared')")


@pytest.mark.asyncio
async def test_legacy_prepared_hold_recovers_only_with_exact_orders_denial(api):
    app, client, peers = api
    await open_lot(api)
    body, _ = edit_body(peers)
    h = machine(peers)
    original = await client.post('/internal/v2/listing-edits/prepare', json=body, headers=h)
    assert original.status_code == 200
    path = BASE + '/' + body['operation_id']
    assert (await client.post(path + '/abort', headers=h)).json()['status'] == 'pending'
    peers.edit_resolutions[body['operation_id']] = proof(body)
    aborted = await client.post(path + '/abort', headers=h)
    assert aborted.json()['phase'] == 'aborted'
    assert (await client.get('/internal/v2/listing-edits/' + body['operation_id'], headers=h)).json() == aborted.json()
    assert (await client.post('/internal/v2/listing-edits/prepare', json=body, headers=h)).json() == original.json()


@pytest.mark.asyncio
@pytest.mark.parametrize('first', ['dispatch', 'reconcile'])
async def test_dispatch_and_expiry_race_have_one_serialized_winner(api, monkeypatch, first):
    app, client, peers = api
    auction, body, _, original = await prepared(api)
    expires = datetime.fromisoformat(original['expires_at'])
    clock_case = ContextVar('clock_case', default='reconcile')
    async def clock(tx):
        return expires + timedelta(microseconds=-1 if clock_case.get() == 'dispatch' else 0)
    monkeypatch.setattr(recovery(app), 'server_now', clock)
    path, h = BASE + '/' + body['operation_id'], machine(peers)
    async def invoke(name):
        token = clock_case.set(name)
        try:
            return await client.post(path + '/' + name, headers=h)
        finally:
            clock_case.reset(token)
    names = [first, 'reconcile' if first == 'dispatch' else 'dispatch']
    replies = await asyncio.gather(*(invoke(name) for name in names))
    values = [reply.json() for reply in replies]
    assert not ({value['phase'] for value in values} >= {'dispatched', 'aborted'}), values
    async with app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM auction_listing_edits')
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction)
        if row['state'] == 'aborted':
            assert row['dispatched_at'] is None and lot['mode'] == 'bidding' and lot['revision'] == 3
        else:
            assert row['dispatched_at'] is not None and lot['mode'] == 'listing_edit_pending' and lot['revision'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('version', [2, 3])
async def test_fixed_price_no_lot_edit_commits_as_pass_through_and_replays(api, version):
    app, client, peers = api
    peers.facts = {'sale_mode': 'fixed_price', 'price_minor': 10000}
    body, facts = edit_body(peers)
    if version == 3:
        body.update(orders_operation_key=body['operation_id'], orders_expected_revision=1, lease_seconds=30)
    base = f'/internal/v{version}/listing-edits'
    h = machine(peers)
    prepared = await client.post(base + '/prepare', json=body, headers=h)
    assert prepared.status_code == 200 and prepared.json()['auction_id'] is None
    path = base + '/' + body['operation_id']
    if version == 3:
        assert (await client.post(path + '/dispatch', headers=h)).json()['phase'] == 'dispatched'
    peers.listing_revision = peers.watch_listing_revision = 2
    peers.facts, peers.watch_revision, peers.watch_status, peers.committed = facts, 3, 'available', True
    committed = await client.post(path + '/commit', json={'listing_revision': 2}, headers=h)
    assert committed.status_code == 200 and committed.json()['phase'] == 'committed', committed.text
    assert committed.json()['auction_id'] is None and committed.json()['auction_revision'] is None
    assert (await client.post(path + '/commit', json={'listing_revision': 2}, headers=h)).json() == committed.json()
    assert (await client.get(path, headers=h)).json() == committed.json()
    assert (await client.post(base + '/prepare', json=body, headers=h)).json() == prepared.json()
    assert not peers.intents  # No invented auction_open, bid, allocation or charge.
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_lots') == 0
        assert await tx.fetchval("SELECT count(*) FROM auction_listing_edits WHERE state='prepared'") == 0


@pytest.mark.asyncio
async def test_v3_recovery_requires_service_purpose_and_dispatch_before_commit(api):
    _, client, peers = api
    _, body, _, _ = await prepared(api)
    path = BASE + '/' + body['operation_id']
    for action in ['dispatch', 'abort', 'reconcile']:
        assert (await client.post(path + '/' + action, headers=headers(BUYER))).status_code == 401
        assert (await client.post(path + '/' + action, headers=machine(peers, 'orders'))).status_code == 403
        assert (await client.post(path + '/' + action, headers=machine(peers, purpose='access'))).status_code == 403
    response = await client.post(path + '/commit', json={'listing_revision': 2}, headers=machine(peers))
    assert response.status_code == 409 and response.json()['error']['code'] == 'dispatch_required'
