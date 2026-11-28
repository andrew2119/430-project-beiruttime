"""Canonical Auction DB with versioned peer fixtures; not all-service acceptance."""
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import asyncpg
import httpx
import pytest
from bt_bulkheads import DependencyClient
from bt_runtime.app.settings import Settings
from bt_runtime.app.db import unit_of_work
from service_app.main import create_app
from service_app.dependencies import Dependencies
from service_app.kernel import transition, extension

SELLER, BUYER, OTHER, LISTING, WATCH = (uuid4() for _ in range(5))


class Peers:
    def __init__(self):
        self.auction = None
        self.committed = False
        self.drop_first = False
        self.quotes = {}
        self.intents = {}
        self.listing_revision = self.watch_listing_revision = self.watch_revision = 1
        self.watch_status = 'available'
        self.facts = {'sale_mode': 'auction'}
        self.v2_available = True
        self.edit_resolutions = {}
        self.orders_resolution_unavailable = False
        self.drop_open_reply = False

    def handle(self, request):
        path, host = request.url.path, request.url.host
        if host == 'identity':
            who = request.headers['authorization'].removeprefix('Bearer ')
            if who not in (str(SELLER), str(BUYER), str(OTHER)):
                return httpx.Response(401)
            return httpx.Response(200, json={'actor': {'subject_id': who, 'session_id': 'test'},
                'roles': ['buyer', 'private_seller'], 'permissions': ['identity.listings.publish']})
        if host == 'catalog':
            return httpx.Response(200, json={'id': str(LISTING), 'revision': self.listing_revision, 'physical_watch_id': str(WATCH),
                'seller_id': str(SELLER), 'organization_id': None, 'registration': {'watch_id': str(WATCH),
                'listing_id': str(LISTING), 'sale_mode': 'auction', 'revision': self.watch_revision}, 'facts': self.facts, 'status': 'published'})
        if host == 'orders':
            if '/listing-edit-operations/' in path:
                if self.orders_resolution_unavailable:
                    return httpx.Response(503)
                key = request.url.params['operation_key']
                return httpx.Response(200, json=self.edit_resolutions[key]) if key in self.edit_resolutions else httpx.Response(404)
            if path.startswith('/internal/v2/') and not self.v2_available:
                return httpx.Response(404)
            if '/operations/' in path:
                operation = path.rsplit('/', 1)[-1]
                return httpx.Response(200, json=self.intents[operation]) if operation in self.intents else httpx.Response(404)
            if request.method == 'GET':
                result = {'watch_id': str(WATCH), 'listing_id': str(LISTING), 'listing_revision': self.watch_listing_revision,
                    'source_id': self.auction, 'status': self.watch_status,
                    'sale_mode': {'auction': 'auction', 'fixed_price': 'fixed', 'offer': 'seller_base'}[self.facts['sale_mode']],
                    'auction_committed': self.committed, 'revision': self.watch_revision}
                if path.startswith('/internal/v1/'):
                    result = {key: result[key] for key in ('watch_id', 'listing_id', 'revision', 'status', 'sale_mode')}
                    result['source_matches'] = self.auction is not None and request.url.params.get('source_id') == self.auction
                return httpx.Response(200, json=result)
            body = json.loads(request.content)
            legacy = path.startswith('/internal/v1/')
            assert legacy or path == '/internal/v2/commitments'
            key = request.headers['idempotency-key']
            if key in self.intents:
                return httpx.Response(200, json=self.intents[key])
            if body['expected_revision'] != self.watch_revision:
                self.intents[key] = {'id': str(uuid4()), 'status': 'denied'}
                return httpx.Response(200, json=self.intents[key])
            kind = 'auction_open' if legacy else body['kind']
            if kind == 'auction_open':
                self.auction = body['source_id']
                self.watch_status = 'fenced'
                self.committed = legacy
            else:
                assert kind == 'first_bid'
                self.committed = True
            self.watch_revision += 1
            self.intents[key] = {'id': str(uuid4()), 'status': 'succeeded'}
            if kind == 'first_bid' and self.drop_first:
                self.drop_first = False
                return httpx.Response(503)
            if kind == 'auction_open' and self.drop_open_reply:
                self.drop_open_reply = False
                return httpx.Response(503)
            return httpx.Response(200, json=self.intents[key])
        if host == 'pricing':
            return httpx.Response(200, json=self.quotes[path.rsplit('/', 1)[-1]])
        return httpx.Response(404)

    def quote(self, auction, actor, amount, revision):
        quote_id = str(uuid4())
        now = datetime.now(timezone.utc)
        fee = (amount * 300 + 5000) // 10000
        self.quotes[quote_id] = {'id': quote_id, 'owner_id': str(actor), 'subject_id': str(auction), 'subject_revision': revision,
            'revision': 1, 'purpose': 'bid', 'currency': 'USD', 'price_minor': amount, 'buyer_fee_minor': fee,
            'shipping_minor': 0, 'tax_minor': 0, 'payable_minor': amount + fee, 'schedule_id': 'usd-v2',
            'source': 'sample', 'source_verified': False, 'sample': True, 'minor_unit_exponent': 2, 'rounding': 'half_up',
            'created_at': (now - timedelta(seconds=2)).isoformat(), 'reviewed_at': (now - timedelta(seconds=1)).isoformat(),
            'expires_at': (now + timedelta(minutes=15)).isoformat()}
        return quote_id


@pytest.fixture
async def api(database_url):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = signing.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public = signing.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    peers = Peers()
    peers.service_private = key
    deps = Dependencies({name: DependencyClient(name, 'http://' + name, transport=httpx.MockTransport(peers.handle))
                         for name in ('identity', 'catalog', 'orders', 'pricing')}, service_key=key)
    app = create_app(Settings(database_url=database_url, service_name='auction', service_auth_public_key=public), deps)
    async with app.router.lifespan_context(app):
        # Frozen auction-policy/v1 fixture; runtime owns atomic invocation/commit.
        def policy(state):
            end = datetime.fromisoformat(state['ends_at'])
            now = datetime.fromisoformat(state['server_time'])
            changed = state['extension_policy'] == 'last-two-minutes.v1' and 0 < (end - now).total_seconds() <= 120
            return {'ends_at': (end + timedelta(seconds=120) if changed else end).isoformat(),
                    'end_version': state['end_version'] + int(changed), 'extended': changed}
        app.state.hooks['auction.policy.accepted-bid.v1'] = policy
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield app, client, peers


def headers(actor=SELLER, key=None):
    return {'Authorization': 'Bearer ' + str(actor), 'Idempotency-Key': key or str(uuid4())}


async def open_lot(api):
    app, client, peers = api
    now = datetime.now(timezone.utc)
    response = await client.post('/v1/auctions', headers=headers(), json={'listing_id': str(LISTING), 'currency': 'USD',
        'opening_minor': 400000, 'reserve_minor': 450000, 'increment_bands': [{'from_minor': 0, 'step_minor': 10000}],
        'starts_at': (now - timedelta(minutes=1)).isoformat(), 'ends_at': (now + timedelta(seconds=100)).isoformat()})
    assert response.status_code == 200, response.text
    auction = UUID(response.json()['auction_id'])
    async with app.state.pool.acquire() as tx:
        # Synthetic policy fixture before bids; real L12 command owns live configuration.
        await tx.execute("UPDATE auction_lots SET extension_policy='last-two-minutes.v1' WHERE id=$1", auction)
    return auction


@pytest.mark.asyncio
async def test_bid_extension_and_outbox_commit_once_and_economics_stay_frozen(api):
    app, client, peers = api
    auction = await open_lot(api)
    original = (await client.get('/v1/auctions/' + str(auction))).json()
    body = {'amount_minor': 400000, 'expected_revision': 1, 'fee_quote_id': peers.quote(auction, BUYER, 400000, 1)}
    h = headers(BUYER, 'bid-and-extend')
    response = await client.post(f'/v1/auctions/{auction}/bids', json=body, headers=h)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'succeeded' and result['end_version'] == 2
    assert datetime.fromisoformat(result['ends_at']) == datetime.fromisoformat(original['ends_at']) + timedelta(seconds=120)
    assert (await client.post(f'/v1/auctions/{auction}/bids', json=body, headers=h)).json() == result
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids WHERE auction_id=$1', auction) == 1
        event = json.loads(await tx.fetchval("SELECT envelope FROM outbox WHERE envelope->>'type'='auction.bid-accepted.v1'"))
        assert 'end_version' not in event['data'] and event['data']['ends_at'] == result['ends_at']
        timing = json.loads(await tx.fetchval("SELECT envelope FROM outbox WHERE envelope->>'type'='auction.timing-updated.v2'"))
        assert timing['data']['end_version'] == 2 and timing['data']['ends_at'] == result['ends_at']
        assert 'maxima' not in json.dumps(event)
        with pytest.raises(asyncpg.CheckViolationError):
            await tx.execute("UPDATE auction_lots SET ends_at=ends_at+interval '120 seconds',end_version=end_version+1 WHERE id=$1", auction)
        with pytest.raises(asyncpg.CheckViolationError):
            await tx.execute('UPDATE auction_lots SET reserve_minor=500000 WHERE id=$1', auction)


@pytest.mark.asyncio
async def test_first_bid_lost_reply_holds_all_modes_then_same_intent_recovers(api):
    app, client, peers = api
    auction = await open_lot(api)
    peers.drop_first = True
    body = {'amount_minor': 400000, 'expected_revision': 1, 'fee_quote_id': peers.quote(auction, BUYER, 400000, 1)}
    h = headers(BUYER, 'unknown-first-bid')
    first = await client.post(f'/v1/auctions/{auction}/bids', json=body, headers=h)
    assert first.status_code == 503
    pending = (await client.get('/v1/auction-operations/by-key/unknown-first-bid', headers=h)).json()
    assert pending['status'] == 'pending'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT mode FROM auction_lots WHERE id=$1', auction) == 'first_bid_pending'
        assert await tx.fetchval('SELECT count(*) FROM auction_bids WHERE auction_id=$1', auction) == 0
    other = await client.post(f'/v1/auctions/{auction}/bids', json={**body, 'fee_quote_id': peers.quote(auction, OTHER, 400000, 1)}, headers=headers(OTHER))
    assert other.status_code == 409
    recovered = await client.post(f'/v1/auctions/{auction}/bids', json=body, headers=h)
    assert recovered.status_code == 200 and recovered.json()['status'] == 'succeeded'
    assert recovered.json()['operation_id'] == pending['operation_id']
    assert len(peers.intents) == 2  # one open, one stable first-bid fence, no duplicates


@pytest.mark.asyncio
async def test_close_uses_current_version_and_pending_prebid_denies_bids(api):
    app, client, peers = api
    auction = await open_lot(api)
    from bt_contracts_core.errors import PublicError
    async with unit_of_work(app.state.pool) as tx:
        with pytest.raises(PublicError, match='auction_not_ended'):
            await transition(tx, auction, expected_revision=1, expected_end_version=1, from_mode='bidding', to_mode='closed_no_sale')
    async with unit_of_work(app.state.pool) as tx:
        row = await transition(tx, auction, expected_revision=1, expected_end_version=1, from_mode='bidding', to_mode='prebid_pending')
        assert row['revision'] == 2
    response = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(BUYER), json={'amount_minor': 400000,
        'expected_revision': 2, 'fee_quote_id': peers.quote(auction, BUYER, 400000, 2)})
    assert response.status_code == 409
    async with unit_of_work(app.state.pool) as tx:
        with pytest.raises(PublicError):
            await transition(tx, auction, expected_revision=2, expected_end_version=1, from_mode='bidding', to_mode='closed_no_sale')


def test_policy_missing_or_malformed_never_accepts():
    from bt_contracts_core.errors import PublicError
    now = datetime.now(timezone.utc)
    lot = {'extension_policy': 'last-two-minutes.v1', 'ends_at': now + timedelta(seconds=60), 'end_version': 3}
    result = {'bids': [1]}
    with pytest.raises(PublicError):
        extension({}, lot, result, now)
    with pytest.raises(PublicError):
        extension({'auction.policy.accepted-bid.v1': lambda state: {'ends_at': state['ends_at'], 'end_version': 4, 'extended': True}}, lot, result, now)
    assert extension({}, lot, {'bids': []}, now) == (lot['ends_at'], 3)


@pytest.mark.asyncio
async def test_known_first_commit_fences_prebid_before_a_public_receipt(api):
    app, _, _ = api
    auction = await open_lot(api)
    from bt_contracts_core.errors import PublicError
    async with app.state.pool.acquire() as tx:
        await tx.execute('UPDATE auction_lots SET first_bid_confirmed=true WHERE id=$1', auction)
    async with unit_of_work(app.state.pool) as tx:
        with pytest.raises(PublicError, match='first_bid_exists'):
            await transition(tx, auction, expected_revision=1, expected_end_version=1, from_mode='bidding', to_mode='prebid_pending')
    async with app.state.pool.acquire() as tx:
        with pytest.raises(asyncpg.CheckViolationError):
            await tx.execute("UPDATE auction_lots SET mode='prebid_pending' WHERE id=$1", auction)


@pytest.mark.asyncio
@pytest.mark.parametrize('actor,amount', [(SELLER, 400000), (BUYER, 399999)])
async def test_invalid_first_bid_never_prepares_a_remote_commitment(api, actor, amount):
    app, client, peers = api
    auction = await open_lot(api)
    body = {'amount_minor': amount, 'expected_revision': 1, 'fee_quote_id': peers.quote(auction, actor, amount, 1)}
    response = await client.post(f'/v1/auctions/{auction}/bids', json=body, headers=headers(actor))
    assert response.status_code == 409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_first_bid_intents') == 0
    assert not peers.committed


@pytest.mark.asyncio
async def test_pending_key_is_reserved_and_expired_bid_still_reconciles_fence(api, monkeypatch):
    from service_app import first_bid
    app, client, peers = api
    auction = await open_lot(api)
    peers.drop_first = True
    body = {'amount_minor': 400000, 'expected_revision': 1, 'fee_quote_id': peers.quote(auction, BUYER, 400000, 1)}
    h = headers(BUYER, 'expired-pending-bid')
    assert (await client.post(f'/v1/auctions/{auction}/bids', json=body, headers=h)).status_code == 503
    pending = (await client.get('/v1/auction-operations/by-key/expired-pending-bid', headers=h)).json()
    assert pending['status'] == 'pending'
    # The canonical actor/key cannot authorize another resource while pending.
    conflict = await client.post(f'/v1/auctions/{uuid4()}/bids', json=body, headers=h)
    assert conflict.status_code == 409
    async def later(tx):
        return datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(first_bid, 'server_now', later)
    recovered = await client.post(f'/v1/auctions/{auction}/bids', json=body, headers=h)
    assert recovered.status_code == 200 and recovered.json()['status'] == 'denied'
    assert recovered.json()['code'] == 'auction_ended' and recovered.json()['operation_id'] == pending['operation_id']
    async with app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction)
        assert lot['mode'] == 'bidding' and lot['first_bid_confirmed'] is True
        assert await tx.fetchval('SELECT count(*) FROM auction_bids WHERE auction_id=$1', auction) == 0
    assert len(peers.intents) == 2


def machine(peers, subject='catalog', purpose='service'):
    import jwt
    now = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode({'sub': subject, 'type': purpose, 'iss': 'beirut-time-identity', 'aud': 'auction',
        'iat': now, 'exp': now + 60}, peers.service_private, algorithm='RS256')
    return {'Authorization': 'Bearer ' + token}


def edit_body(peers):
    import hashlib
    facts = {**peers.facts, 'reference': 'تجربة R2'}
    digest = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return {'operation_id': str(uuid4()), 'listing_id': str(LISTING), 'watch_id': str(WATCH),
        'listing_revision': peers.listing_revision, 'next_revision': peers.listing_revision + 1, 'facts_digest': digest}, facts


@pytest.mark.asyncio
async def test_listing_edit_freezes_then_rebinds_current_scope_and_replays(api):
    app, client, peers = api
    auction = await open_lot(api)
    body, facts = edit_body(peers)
    h = machine(peers)
    prepared = await client.post('/internal/v2/listing-edits/prepare', json=body, headers=h)
    assert prepared.status_code == 200 and prepared.json()['phase'] == 'prepared', prepared.text
    assert (await client.post('/internal/v2/listing-edits/prepare', json=body, headers=h)).json() == prepared.json()
    held = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(BUYER), json={'amount_minor': 400000,
        'expected_revision': 2, 'fee_quote_id': peers.quote(auction, BUYER, 400000, 2)})
    assert held.status_code == 409
    commit_path = '/internal/v2/listing-edits/' + body['operation_id'] + '/commit'
    assert (await client.post(commit_path, json={'listing_revision': 2}, headers=h)).status_code == 409
    # Frozen provider fixture: actual Catalog revision and completed Orders edit.
    peers.listing_revision = peers.watch_listing_revision = 2
    peers.facts = facts
    peers.watch_revision = 4
    peers.watch_status, peers.auction = 'available', None
    committed = await client.post(commit_path, json={'listing_revision': 2}, headers=h)
    assert committed.status_code == 200 and committed.json()['phase'] == 'committed', committed.text
    assert (await client.post(commit_path, json={'listing_revision': 2}, headers=h)).json() == committed.json()
    assert (await client.post('/internal/v2/listing-edits/prepare', json=body, headers=h)).json() == prepared.json()
    async with app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction)
        assert lot['listing_revision'] == 2 and lot['revision'] == 3 and lot['mode'] == 'bidding'
    assert peers.auction == str(auction) and peers.watch_status == 'fenced'
    assert len(peers.intents) == 2  # opening + one durable refence


@pytest.mark.asyncio
async def test_listing_edit_requires_machine_purpose_and_cannot_race_opening(api):
    app, client, peers = api
    body, facts = edit_body(peers)
    path = '/internal/v2/listing-edits/prepare'
    assert (await client.post(path, json=body, headers=headers(BUYER))).status_code == 401
    assert (await client.post(path, json=body, headers=machine(peers, 'pricing'))).status_code == 403
    assert (await client.post(path, json=body, headers=machine(peers, purpose='access'))).status_code == 403
    result = await client.post(path, json=body, headers=machine(peers))
    assert result.status_code == 200, result.text
    now = datetime.now(timezone.utc)
    opening = {'listing_id': str(LISTING), 'currency': 'USD', 'opening_minor': 400000, 'reserve_minor': None,
        'increment_bands': [{'from_minor': 0, 'step_minor': 10000}], 'starts_at': (now - timedelta(minutes=1)).isoformat(),
        'ends_at': (now + timedelta(hours=1)).isoformat()}
    blocked = await client.post('/v1/auctions', json=opening, headers=headers())
    assert blocked.status_code == 409
    peers.listing_revision = peers.watch_listing_revision = 2
    peers.facts = facts
    peers.watch_revision = 3
    commit_path = '/internal/v2/listing-edits/' + body['operation_id'] + '/commit'
    assert (await client.post(commit_path, json={'listing_revision': 2}, headers=machine(peers))).status_code == 200
    opened = await client.post('/v1/auctions', json=opening, headers=headers())
    assert opened.status_code == 200, opened.text
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT listing_revision FROM auction_lots') == 2


@pytest.mark.asyncio
async def test_legacy_orders_keeps_existing_bid_flow_conservatively_committed(api):
    app, client, peers = api
    peers.v2_available = False
    auction = await open_lot(api)
    response = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(BUYER), json={
        'amount_minor': 400000, 'expected_revision': 1, 'fee_quote_id': peers.quote(auction, BUYER, 400000, 1)})
    assert response.status_code == 200 and response.json()['status'] == 'succeeded', response.text
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_first_bid_intents') == 0
        assert await tx.fetchval('SELECT first_bid_confirmed FROM auction_lots') is True
