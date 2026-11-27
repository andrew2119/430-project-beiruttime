import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_contracts_core.models import Actor
from bt_runtime.app.db import create_pool
from bt_runtime.app.settings import Settings
from bt_runtime.principal import CurrentPrincipal
from service_app.main import create_app
from service_app.dependencies import Dependencies

SELLER, BUYER, OTHER = uuid4(), uuid4(), uuid4()
LISTING, WATCH = uuid4(), uuid4()
_service_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SERVICE_PRIVATE = _service_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).decode()
SERVICE_PUBLIC = _service_key.public_key().public_bytes(serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo).decode()


class Upstreams:
    def __init__(self):
        self.actors = {str(s): CurrentPrincipal(actor=Actor(subject_id=s, session_id='sample-session'),
            permissions=['identity.listings.publish'], roles=['buyer', 'private_seller'])
            for s in (SELLER, BUYER, OTHER)}
        self.quotes = {}
        self.outage = None
        self.contact = True
        self.contact_payload = None
        self.published = True
        self.listing_id, self.watch_id = LISTING, WATCH
        self.listing_organization_id = None
        self.listing_seller_id = SELLER
        self.fenced = True
        self.auction_id = None
        self.commitment_acquired = False
        self.drop_fence_response = False
        self.fence_posts = 0

    def handle(self, request):
        name = request.url.host
        path = request.url.path
        if self.outage == name:
            return httpx.Response(503)
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        if name == 'identity':
            if path == '/internal/v1/principal':
                actor = self.actors.get(token)
                selected = request.url.params.get('organization_id')
                if actor and selected:
                    if UUID(selected) not in actor.organizations:
                        return httpx.Response(403)
                    actor = actor.model_copy(deep=True)
                    actor.actor.organization_id = UUID(selected)
                return httpx.Response(200, json=actor.model_dump(mode='json')) if actor else httpx.Response(403)
            assert path == '/v1/contacts'
            return httpx.Response(200, json=self.contact_payload if self.contact_payload is not None else
                {'revision': 1, 'email_verified': self.contact, 'phone_verified': False, 'pending_challenge': None})
        if name == 'catalog':
            assert path == f'/v1/listings/{self.listing_id}'
            return httpx.Response(200, json={'id': str(self.listing_id), 'physical_watch_id': str(self.watch_id), 'seller_id': str(self.listing_seller_id),
                'organization_id': str(self.listing_organization_id) if self.listing_organization_id else None,
                'registration':{'watch_id':str(self.watch_id),'listing_id':str(self.listing_id),'sale_mode':'auction','revision':1},
                'facts':{'sale_mode':'auction'}, 'status': 'published' if self.published else 'hidden'})
        if name == 'orders':
            try:
                claims = jwt.decode(token, SERVICE_PUBLIC, algorithms=['RS256'], audience='orders', issuer='beirut-time-identity')
                assert claims['sub'] == 'auction' and claims['type'] == 'service'
            except (jwt.InvalidTokenError, AssertionError):
                return httpx.Response(403)
            if request.method == 'POST':
                self.fence_posts += 1
                body = json.loads(request.content)
                assert path == f'/internal/v1/watches/{self.watch_id}/fences'
                assert body['expected_revision'] == 1
                self.auction_id = body['source_id']
                self.commitment_acquired = self.fenced
                if self.drop_fence_response:
                    return httpx.Response(503)
                return httpx.Response(200, json={'status': 'succeeded' if self.fenced else 'denied',
                    'id': str(uuid4()), 'resource_id': str(self.watch_id)})
            return httpx.Response(200, json={'watch_id': str(self.watch_id), 'listing_id': str(self.listing_id),
                'revision': 2 if self.commitment_acquired else 1,
                'status': 'fenced' if self.commitment_acquired else 'available',
                'sale_mode': 'auction' if self.fenced else 'fixed',
                'source_matches': self.commitment_acquired and request.url.params.get('source_id') == self.auction_id})
        if name == 'pricing':
            quote = self.quotes.get(path.rsplit('/', 1)[-1])
            return httpx.Response(200, json=quote) if quote else httpx.Response(404)
        return httpx.Response(404)

    def dependencies(self):
        return Dependencies({name: DependencyClient(name, f'http://{name}', timeout=.5, concurrency=4,
            transport=httpx.MockTransport(self.handle)) for name in ('identity', 'catalog', 'orders', 'pricing')},
            service_key=SERVICE_PRIVATE)

    def quote(self, auction, actor, amount, **overrides):
        key = uuid4()
        now = datetime.now(timezone.utc)
        fee = (amount * 300 + 5000) // 10000
        self.quotes[str(key)] = {'id': str(key), 'owner_id': str(actor), 'subject_id': str(auction),
            'subject_revision': 1, 'revision': 1, 'purpose': 'bid', 'currency': 'USD', 'price_minor': amount,
            'buyer_fee_minor': fee, 'shipping_minor': 0, 'tax_minor': 0, 'payable_minor': amount + fee,
            'schedule_id': 'usd-v2', 'source': 'sample', 'source_verified': False, 'sample': True,
            'minor_unit_exponent': 2, 'rounding': 'half_up',
            'created_at': (now - timedelta(seconds=2)).isoformat(),
            'reviewed_at': (now - timedelta(seconds=1)).isoformat(),
            'expires_at': (now + timedelta(hours=1)).isoformat(), **overrides}
        return str(key)


@pytest_asyncio.fixture
async def api(database_url):
    upstream = Upstreams()
    app = create_app(Settings(database_url=database_url, modules_path=Path('/app/modules')), upstream.dependencies())
    app.state.pool = await create_pool(database_url)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, app, upstream
    await app.state.pool.close()
    await app.state.auction.dependencies.close()


def headers(actor, key=None):
    return {'Authorization': 'Bearer ' + str(actor), 'Idempotency-Key': key or str(uuid4())}


def rules(**overrides):
    now = datetime.now(timezone.utc)
    return {'listing_id': str(LISTING), 'currency': 'USD', 'opening_minor': 400000,
        'increment_bands': [{'from_minor': 0, 'step_minor': 10000}], 'reserve_minor': 450000,
        'starts_at': (now - timedelta(minutes=1)).isoformat(),
        'ends_at': (now + timedelta(hours=1)).isoformat(), **overrides}


async def open_auction(api, **overrides):
    client, _, _ = api
    result = await client.post('/v1/auctions', json=rules(**overrides), headers=headers(SELLER))
    assert result.status_code == 200, result.text
    return result.json()['auction_id']


async def bid(api, auction, actor=BUYER, amount=400000, revision=1, key=None, **quote_overrides):
    client, _, upstream = api
    return await client.post(f'/v1/auctions/{auction}/bids', headers=headers(actor, key), json={
        'amount_minor': amount, 'expected_revision': revision,
        'fee_quote_id': upstream.quote(auction, actor, amount, **{'subject_revision': revision, **quote_overrides})})


async def test_create_is_unique_and_public_projection_is_private(api):
    client, app, _ = api
    command = rules()
    auth = headers(SELLER, 'open-lot')
    first = await client.post('/v1/auctions', json=command, headers=auth)
    replay = await client.post('/v1/auctions', json=command, headers=auth)
    assert first.json() == replay.json()
    again = await client.post('/v1/auctions', json=command, headers=headers(SELLER))
    assert again.json()['auction_id'] == first.json()['auction_id']
    text = (await client.get('/v1/auctions')).text
    assert str(SELLER) not in text and 'reserve_minor' not in text
    assert '450000' not in text and 'server_time' in text
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_lots') == 1
        assert await tx.fetchval('SELECT count(*) FROM outbox') == 1


async def test_bid_increment_and_frozen_rules(api):
    client, _, _ = api
    auction = await open_auction(api)
    assert (await bid(api, auction)).json()['status'] == 'succeeded'
    low = (await bid(api, auction, OTHER, 400000, 2)).json()
    assert low['code'] == 'bid_too_low' and low['next_minimum_minor'] == 410000
    accepted = (await bid(api, auction, OTHER, 410000, 2)).json()
    assert accepted['status'] == 'succeeded' and accepted['accepted_sequence'] == 2
    command = rules()
    command.pop('listing_id')
    result = await client.patch(f'/v1/auctions/{auction}/rules', json=command,
        headers={**headers(SELLER), 'If-Match': '3'})
    assert result.status_code == 409 and result.json()['error']['code'] == 'rules_frozen'
    history = (await client.get(f'/v1/auctions/{auction}/history')).json()
    assert [b['sequence'] for b in history['items']] == [1, 2]
    assert str(BUYER) not in json.dumps(history)


async def test_same_operation_acknowledged_once_and_reconciles(api):
    client, app, upstream = api
    auction = await open_auction(api)
    command = {'amount_minor': 400000, 'expected_revision': 1,
        'fee_quote_id': upstream.quote(auction, BUYER, 400000)}
    first = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(BUYER, 'same-op'), json=command)
    same = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(BUYER, 'same-op'), json=command)
    assert first.json() == same.json()
    changed = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(BUYER, 'same-op'),
        json={**command, 'amount_minor': 410000})
    assert changed.status_code == 409
    op = first.json()['operation_id']
    assert (await client.get(f'/v1/auctions/{auction}/operations/{op}', headers=headers(OTHER))).status_code == 404
    assert (await client.get('/v1/auction-operations/by-key/same-op', headers=headers(BUYER))).json() == first.json()
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 1
        assert await tx.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='auction.bid-accepted.v1'") == 1


async def test_equal_race_has_one_authoritative_winner(api):
    auction = await open_auction(api)
    responses = await asyncio.gather(bid(api, auction, BUYER), bid(api, auction, OTHER))
    outcomes = [r.json() for r in responses]
    assert sorted(o['status'] for o in outcomes) == ['denied', 'succeeded']
    assert {o['accepted_sequence'] for o in outcomes} == {1}


@pytest.mark.parametrize('reason', ['self', 'low', 'late', 'early', 'stale', 'contact', 'fee', 'hidden', 'fence'])
async def test_denied_bids_do_not_write_history(api, reason):
    client, app, upstream = api
    auction = await open_auction(api)
    actor, amount, revision, quote = BUYER, 400000, 1, {}
    if reason == 'self':
        actor = SELLER
    elif reason == 'low':
        amount = 399999
    elif reason == 'stale':
        revision = 7
    elif reason == 'contact':
        amount, upstream.contact = 1000000, False
    elif reason == 'fee':
        quote = {'subject_id': str(OTHER)}
    elif reason == 'hidden':
        upstream.published = False
    elif reason == 'fence':
        upstream.fenced = False
    elif reason in ('late', 'early'):
        async with app.state.pool.acquire() as tx:
            if reason == 'late':
                await tx.execute("UPDATE auction_lots SET starts_at=now()-interval '1 hour',ends_at=clock_timestamp()")
            else:
                await tx.execute("UPDATE auction_lots SET starts_at=now()+interval '1 hour',ends_at=now()+interval '2 hours'")
    response = await bid(api, auction, actor, amount, revision, **quote)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'denied'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 0
        assert await tx.fetchval("SELECT count(*) FROM auction_operations WHERE outcome->>'status'='denied'") == 1


@pytest.mark.parametrize(('overrides', 'code'), [
    ({'reviewed_at': None}, 'fee_review_required'),
    ({'owner_id': str(OTHER)}, 'fee_preview_required'),
    ({'purpose': 'purchase'}, 'fee_preview_required'),
    ({'subject_revision': 2}, 'fee_preview_required'),
    ({'currency': 'LBP'}, 'fee_preview_required'),
    ({'source': 'listing'}, 'fee_preview_required'),
    ({'sample': False}, 'fee_preview_required'),
])
async def test_retained_pricing_snapshot_must_bind_reviewed_bid(api, overrides, code):
    _, app, _ = api
    auction = await open_auction(api)
    response = await bid(api, auction, **overrides)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'denied' and response.json()['code'] == code
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 0
        assert await tx.fetchval('SELECT count(*) FROM auction_operations WHERE subject_id=$1', BUYER) == 1


async def test_malformed_pricing_snapshot_is_unavailable_not_acknowledged(api):
    _, app, _ = api
    auction = await open_auction(api)
    response = await bid(api, auction, payable_minor=1)
    assert response.status_code == 503
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 0
        assert await tx.fetchval('SELECT count(*) FROM auction_operations WHERE subject_id=$1', BUYER) == 0


async def test_expired_retained_quote_is_not_bid_authority(api):
    auction = await open_auction(api)
    now = datetime.now(timezone.utc)
    result = await bid(api, auction, created_at=(now - timedelta(hours=2)).isoformat(),
        reviewed_at=(now - timedelta(hours=1)).isoformat(),
        expires_at=(now - timedelta(seconds=1)).isoformat())
    assert result.json()['code'] == 'fee_preview_required'


async def test_quote_expiry_rechecked_after_current_contact_call(api, monkeypatch):
    _, app, _ = api
    auction = await open_auction(api)
    async def slow_contact(request):
        await asyncio.sleep(.3)
    monkeypatch.setattr(app.state.auction.dependencies, 'contact', slow_contact)
    result = await bid(api, auction, amount=1000000,
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=.2)).isoformat())
    assert result.json()['code'] == 'fee_preview_required'


@pytest.mark.parametrize('channel', ['email', 'phone'])
async def test_current_verified_contact_flags_qualify_high_value_bid(api, channel):
    _, _, upstream = api
    auction = await open_auction(api)
    upstream.contact_payload = {'email_verified': channel == 'email', 'phone_verified': channel == 'phone'}
    assert (await bid(api, auction, amount=1000000)).json()['status'] == 'succeeded'


async def test_pending_contact_never_qualifies_and_recipients_are_not_stored(api):
    _, app, upstream = api
    auction = await open_auction(api)
    upstream.contact_payload = {'email_verified': False, 'phone_verified': False,
        'email': 'sample-pending@example.test', 'pending_challenge': {'state': 'pending'}}
    assert (await bid(api, auction, amount=1000000)).json()['code'] == 'verified_contact_required'
    async with app.state.pool.acquire() as tx:
        assert 'example.test' not in str(await tx.fetch('SELECT outcome FROM auction_operations'))
        assert 'example.test' not in str(await tx.fetch('SELECT envelope FROM outbox'))


async def test_malformed_contact_read_is_unavailable_not_a_refusal(api):
    _, _, upstream = api
    auction = await open_auction(api)
    upstream.contact_payload = {'verified': True, 'email_verified': 'true', 'phone_verified': False}
    assert (await bid(api, auction, amount=1000000)).status_code == 503


async def test_dependency_outage_is_not_false_acknowledgement(api):
    _, app, upstream = api
    auction = await open_auction(api)
    upstream.outage = 'orders'
    result = await bid(api, auction)
    assert result.status_code == 503
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 0
    upstream.outage = None
    assert (await bid(api, auction)).json()['status'] == 'succeeded'


async def test_permission_and_same_business_self_bid(api):
    _, _, upstream = api
    auction = await open_auction(api)
    upstream.actors[str(BUYER)].roles = []
    assert (await bid(api, auction)).status_code == 403
    upstream.actors[str(BUYER)].roles = ['buyer']
    upstream.actors[str(BUYER)].organizations = [uuid4()]
    upstream.actors[str(BUYER)].actor.organization_id = upstream.actors[str(BUYER)].organizations[0]
    assert (await bid(api, auction)).status_code == 403


async def test_hook_runs_inside_transaction_and_maxima_never_project(api):
    client, app, upstream = api
    auction = await open_auction(api)
    def calculate(state, command):
        assert state['sequence'] == 0
        return {'leader_id': command['bidder_id'], 'current_minor': 400000,
            'maxima': [{'bidder_id': command['bidder_id'], 'amount_minor': 450000, 'sequence': command['sequence']}],
            'bids': [{'bidder_id': command['bidder_id'], 'amount_minor': 400000, 'automatic': True}]}
    app.state.hooks['auction.proxy.v1'] = calculate
    # Exercise the same public engine entrypoint L06 routes call, through a temporary test-only route.
    from fastapi import Request
    from bt_contracts.auction.core.models import BidCommand
    @app.post('/test/maximum/{auction_id}')
    async def maximum(auction_id: UUID, command: BidCommand, request: Request):
        return await app.state.auction.submit(request, auction_id, command, kind='maximum')
    result = await client.post(f'/test/maximum/{auction}', headers=headers(BUYER), json={
        'amount_minor': 450000, 'expected_revision': 1, 'fee_quote_id': upstream.quote(auction, BUYER, 450000)})
    assert result.status_code == 200 and result.json()['current_minor'] == 400000
    for path in (f'/v1/auctions/{auction}', f'/v1/auctions/{auction}/history', '/v1/my-bids'):
        raw = (await client.get(path, headers=headers(BUYER))).text
        assert '450000' not in raw and 'maxima' not in raw
    async with app.state.pool.acquire() as tx:
        assert '450000' not in str(await tx.fetch('SELECT envelope FROM outbox'))


@pytest.mark.parametrize('amount', [1.5, True, '400000', -1, 9000000000000001])
async def test_money_is_bounded_integer(api, amount):
    client, _, upstream = api
    auction = await open_auction(api)
    response = await client.post(f'/v1/auctions/{auction}/bids', headers=headers(BUYER), json={
        'amount_minor': amount, 'expected_revision': 1, 'fee_quote_id': str(uuid4())})
    assert response.status_code == 422
