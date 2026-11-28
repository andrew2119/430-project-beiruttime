import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json
import time
from typing import Literal
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import jwt
from pydantic import AwareDatetime, StrictBool, StrictInt
import pytest

from bt_bulkheads import DependencyClient
from bt_contracts_core.models import Actor, Contract
from bt_events import EventEnvelope, enqueue
from bt_runtime.event_http import build_event_router
from bt_runtime.modules import discover
from bt_runtime.principal import CurrentPrincipal
from conftest import ROOT


@pytest.mark.asyncio
@pytest.mark.parametrize('runtime', ['auction'], indirect=True)
async def test_auction_relay_uses_fixed_paths_and_service_audiences(runtime, monkeypatch):
    module = next(module for module in discover(ROOT / 'services/auction/modules') if module.id == 'L05.a-rules')
    relay = module.load('workers.py:relay')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv('BT_SERVICE_AUTH_PRIVATE_KEY', pem)
    stop = asyncio.Event()
    issuer = 'test-issuer'
    destinations = {
        'communications': ('communications', '/internal/v1/events', ('auction.bid-accepted.v1',)),
        'catalog': ('catalog', '/internal/v1/auction/events', ('auction.opened.v1', 'auction.rules-updated.v1')),
        'bid-notices-v2': ('communications', '/internal/v1/events', ('auction.bid-outbid.v2',)),
        'auction-timing-v2': ('auction', '/internal/v1/events', ('auction.timing-updated.v2',
            'auction.listing-revised.v2', 'auction.listing-edit-aborted.v3')),
    }
    seen = set()

    async def receive(client, method, path, *, json, headers):
        service, expected_path, kinds = destinations[client.dependency]
        claims = jwt.decode(headers['Authorization'].split()[1], key.public_key(),
                            algorithms=['RS256'], issuer=issuer, audience=service)
        assert claims['sub'] == 'auction' and claims['type'] == 'service'
        assert (method, path) == ('POST', expected_path) and json['type'] in kinds
        seen.add((client.dependency, json['type']))

    class Relay:
        def __init__(self, pool, clients, *, headers, **kwargs):
            assert set(clients) == destinations.keys()
            self.clients = clients
            self.headers = headers

        async def tick(self):
            for name, client in self.clients.items():
                for kind in destinations[name][2]:
                    await client.request('POST', '/internal/v1/events', json={'type': kind}, headers=self.headers(name))
            stop.set()

    monkeypatch.setattr(DependencyClient, 'request', receive)
    monkeypatch.setitem(relay.__globals__, 'OutboxRelay', Relay)
    app = SimpleNamespace(state=SimpleNamespace(pool=None, settings=SimpleNamespace(auth_issuer=issuer)))
    await relay(app, stop)
    assert seen == {(name, kind) for name, (_, _, kinds) in destinations.items() for kind in kinds}


class CatalogIncrementBand(Contract):
    from_minor: StrictInt
    step_minor: StrictInt


class CatalogAuctionSnapshot(Contract):
    id: UUID
    listing_id: UUID
    currency: Literal['USD', 'LBP']
    opening_minor: StrictInt
    current_minor: StrictInt
    next_minimum_minor: StrictInt
    increment_bands: list[CatalogIncrementBand]
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    server_time: AwareDatetime
    revision: StrictInt
    accepted_sequence: StrictInt
    rules_version: str
    extension_policy: str
    high_value_minor: StrictInt
    reserve_set: StrictBool
    leader: str | None
    status: Literal['live', 'scheduled', 'ended']


class RouteStore:
    def __init__(self, now):
        self.now = now
        self.lot = None
        self.operations = {}
        self.outbox = {}
        self.inbox = set()

    @asynccontextmanager
    async def acquire(self, **kwargs):
        yield self

    @asynccontextmanager
    async def transaction(self, **kwargs):
        yield

    async def fetchrow(self, sql, *args):
        if 'FROM auction_operations' in sql:
            return self.operations.get(args)
        if 'FROM auction_lots' in sql:
            return self.lot
        if sql.startswith('INSERT INTO auction_lots'):
            (auction, listing, watch, seller, organization, currency, opening, reserve,
             bands, starts, ends, commitment, high_value, listing_revision, is_demo) = args
            assert is_demo is False and commitment == str(auction)
            self.lot = dict(id=auction, listing_id=listing, watch_id=watch, seller_id=seller,
                seller_organization_id=organization, currency=currency, opening_minor=opening,
                reserve_minor=reserve, increment_bands=bands, starts_at=starts, ends_at=ends,
                commitment_id=commitment, high_value_minor=high_value, listing_revision=listing_revision,
                revision=1, accepted_sequence=0, current_minor=0, leader_id=None,
                rules_version='test-rules', extension_policy='test-policy', mode='bidding')
            return self.lot
        if sql.startswith('UPDATE auction_lots'):
            _, currency, opening, reserve, bands, starts, ends = args
            self.lot.update(currency=currency, opening_minor=opening, reserve_minor=reserve,
                            increment_bands=bands, starts_at=starts, ends_at=ends, revision=2)
            return self.lot
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if 'clock_timestamp()' in sql:
            return self.now
        if 'FROM auction_listing_edits' in sql:
            return False
        if 'SELECT EXISTS(SELECT 1 FROM auction_operations' in sql:
            return any(json.loads(row['outcome'])['status'] == 'pending'
                       for row in self.operations.values())
        if 'SELECT EXISTS(SELECT 1 FROM auction_lots' in sql:
            return self.lot is not None and self.lot['listing_id'] == args[0]
        if 'FROM auction_publication_watermarks' in sql:
            return None
        if 'INSERT INTO inbox' in sql:
            consumer, event_id, source = args
            assert consumer == 'catalog.auction' and source == 'auction'
            if event_id not in self.inbox:
                self.inbox.add(event_id)
                return event_id
            return None
        raise AssertionError(sql)

    async def fetch(self, sql, limit, lease, seconds, destinations):
        assert 'FOR UPDATE SKIP LOCKED' in sql
        return [row for row in self.outbox.values()
                if row['destination'] in destinations and row['state'] == 'pending'][:limit]

    async def execute(self, sql, *args):
        if sql.startswith('INSERT INTO outbox'):
            event, destination, envelope = args
            self.outbox[event] = dict(id=event, destination=destination, envelope=json.loads(envelope),
                                      attempts=1, state='pending')
        elif sql.startswith('UPDATE outbox'):
            self.outbox[args[0]]['state'] = 'delivered' if 'delivered_at=now()' in sql else 'retry'
            return 'UPDATE 1'
        elif sql.startswith('INSERT INTO auction_operations'):
            operation, actor, org, key, digest, auction, outcome = args
            assert (actor, key) not in self.operations
            self.operations[actor, key] = dict(id=operation, organization_id=org, request_hash=digest,
                                               auction_id=auction, outcome=outcome)
        elif sql.startswith('UPDATE auction_operations'):
            operation, outcome = args
            row = next(row for row in self.operations.values() if row['id'] == operation)
            assert json.loads(row['outcome'])['status'] == 'pending'
            row['outcome'] = outcome
        else:
            assert sql.startswith('SELECT pg_advisory_xact_lock')


@pytest.mark.asyncio
@pytest.mark.parametrize('runtime', ['auction'], indirect=True)
async def test_catalog_accepts_auction_command_events(runtime, monkeypatch):
    from bt_contracts.auction.core.models import AuctionRules, Band, CreateAuction
    from service_app.engine import AuctionEngine

    modules = ROOT / 'services/auction/modules'
    module = next(module for module in discover(modules) if module.id == 'L05.a-rules')
    relay = module.load('workers.py:relay')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv('BT_SERVICE_AUTH_PRIVATE_KEY', pem)

    catalog = FastAPI()
    issuer = 'test-issuer'
    catalog.state.settings = SimpleNamespace(
        auth_issuer=issuer, service_name='catalog', service_auth_public_key=key.public_key(),
    )
    received = {}

    async def invalidate(tx, event):
        snapshot = CatalogAuctionSnapshot.model_validate(event.data)
        if event.subject != str(snapshot.id):
            raise HTTPException(422)
        received[event.type] = event

    opened_type = 'auction.opened.v1'
    updated_type = 'auction.rules-updated.v1'
    catalog_path = '/internal/v1/auction/events'
    subscription = build_event_router('catalog.auction', {
        opened_type: ('auction', invalidate),
        updated_type: ('auction', invalidate),
    })
    catalog.post(catalog_path)(subscription.routes[0].endpoint)

    transport = ASGITransport(app=catalog)
    stop = asyncio.Event()
    statuses = []

    @catalog.middleware('http')
    async def track_delivery(request, call_next):
        response = await call_next(request)
        statuses.append(response.status_code)
        # The relay sends every catalog event to its one path, so the subscription itself refuses an unrouted type.
        assert request.url.path == catalog_path
        if len(statuses) in (2, 3):
            stop.set()
        return response

    original_init = DependencyClient.__init__

    def local_client(self, dependency, base_url, **kwargs):
        original_init(self, dependency, base_url, transport=transport, **kwargs)

    monkeypatch.setattr(DependencyClient, '__init__', local_client)
    listing, watch, seller = (uuid4() for _ in range(3))
    starts = {}
    principal = CurrentPrincipal(
        actor=Actor(subject_id=seller, session_id='test-session'),
        permissions=['identity.listings.publish'],
    )

    class Dependencies:
        async def principal(self, request):
            return principal

        async def listing(self, request, listing_id):
            assert listing_id == listing
            return {'id': str(listing), 'watch_id': str(watch), 'seller_id': str(seller),
                    'status': 'published', 'revision': 1, 'is_demo': False, 'seller_organization_id': None}

        async def fence_state(self, request, watch_id, listing_id, auction_id):
            assert str(watch_id) == str(watch) and listing_id == listing
            if auction_id not in starts:
                return dict(api_version=2, status='available', listing_revision=1, revision=7)
            return dict(api_version=2, status='fenced', listing_revision=1, revision=8,
                        source_id=str(auction_id), source_kind='auction_open', auction_committed=False)

        async def bid_admission(self, request, tx, current):
            assert tx is pool and current == principal and request.state.request_id == 'test-open'

        async def start_commitment(self, request, intent, organization):
            row = pool.operations[seller, 'test-open']
            assert json.loads(row['outcome']) == intent and intent['code'] == 'auction_start_pending'
            assert (intent['listing_id'], intent['watch_id'], intent['watch_revision'], organization) == (
                str(listing), str(watch), 7, None,
            )
            starts[UUID(intent['auction_id'])] = intent
            return dict(status='succeeded', id=str(uuid4()))

        async def check_fence(self, request, lot):
            assert lot['id'] in starts and lot['commitment_id'] == str(lot['id'])

    engine = AuctionEngine(Dependencies())
    now = datetime.now(timezone.utc)
    pool = RouteStore(now)
    catalog.state.pool = pool
    app = SimpleNamespace(state=SimpleNamespace(pool=pool, settings=SimpleNamespace(auth_issuer=issuer)))
    command = CreateAuction(
        listing_id=listing, currency='USD', opening_minor=400, reserve_minor=800,
        increment_bands=[Band(from_minor=0, step_minor=50)],
        starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1),
    )

    def request(operation, **headers):
        return SimpleNamespace(app=app, headers={'idempotency-key': operation, **headers},
                               state=SimpleNamespace(request_id=operation))

    opened = await engine.create(request('test-open'), command)
    auction = UUID(opened['auction_id'])
    assert opened['status'] == 'succeeded' and set(starts) == {auction}
    assert json.loads(pool.operations[seller, 'test-open']['outcome']) == opened
    updated = await engine.update_rules(
        request('test-update', **{'if-match': str(opened['auction']['revision'])}), auction,
        AuctionRules(**command.model_dump(exclude={'listing_id', 'opening_minor'}), opening_minor=500),
    )
    await asyncio.wait_for(relay(app, stop), timeout=5)
    assert statuses == [200, 200]
    stop.clear()

    unknown = EventEnvelope(type='auction.unknown.v1', source='auction', subject=str(auction),
                            request_id='test-unknown', data=opened['auction'])
    await enqueue(pool, unknown, ['catalog'])

    await asyncio.wait_for(relay(app, stop), timeout=5)
    assert statuses == [200, 200, 403]
    assert set(received) == {opened_type, updated_type}
    assert received[opened_type].data['revision'] == 1
    assert received[updated_type].data['revision'] == 2
    assert received[updated_type].data['opening_minor'] == 500
    for kind, result, request_id in (
        (opened_type, opened, 'test-open'), (updated_type, updated, 'test-update'),
    ):
        event = received[kind]
        assert event.source == 'auction' and event.subject == str(auction)
        assert event.request_id == request_id
        assert event.data == result['auction']

    assert set(pool.outbox) == {unknown.id, *(event.id for event in received.values())}
    assert all(row['destination'] == 'catalog' for row in pool.outbox.values())
    assert pool.outbox[unknown.id]['state'] == 'retry'
    assert all(pool.outbox[event.id]['state'] == 'delivered' for event in received.values())
    assert pool.inbox == {event.id for event in received.values()}

    token = jwt.encode({'sub': 'orders', 'type': 'service', 'iss': issuer, 'aud': 'catalog',
                        'iat': int(time.time()), 'exp': int(time.time()) + 60}, key, algorithm='RS256')
    async with AsyncClient(transport=transport, base_url='http://catalog') as client:
        for event in received.values():
            wrong_source = event.model_copy(update={'id': uuid4(), 'source': 'orders'})
            response = await client.post(catalog_path, json=wrong_source.model_dump(mode='json'),
                                         headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == 403
