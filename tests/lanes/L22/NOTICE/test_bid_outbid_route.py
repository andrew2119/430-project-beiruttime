from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
import jwt
import pytest

from bt_contracts.auction.core.models import BidCommand
from bt_contracts_core.models import Actor
from bt_events import EventEnvelope
from bt_runtime.app.settings import Settings
from bt_runtime.app.main import create_app
from bt_runtime.modules import discover
from bt_runtime.principal import CurrentPrincipal


@pytest.mark.asyncio
async def test_newer_outbid_reconciles_the_accepted_bid_occurrence(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    settings = Settings(database_url='postgresql://unused/unused', modules_path=tmp_path,
                        service_name='communications', service_auth_public_key=public)
    app = create_app(settings)
    root = Path(__file__).resolve().parents[4]
    module = next(module for module in discover(root / 'services/communications/modules')
                  if module.id == 'L05.bid-notices')
    app.include_router(module.load('routes.py:router'))
    auction, bidder, lot, emitted = await submit_beaten_challenger(monkeypatch, root)
    accepted = emitted['communications']
    newer = emitted['bid-notices-v2']
    timing = emitted['auction-timing-v2']
    assert accepted.type == 'auction.bid-accepted.v1'
    assert newer.type == 'auction.bid-outbid.v2'
    assert timing.type == 'auction.timing-updated.v2'
    facts = newer.data

    class Store:
        def __init__(self):
            self.receipts = set()
            self.notices = {}

        @asynccontextmanager
        async def acquire(self, **kwargs):
            yield self

        @asynccontextmanager
        async def transaction(self, **kwargs):
            previous = self.receipts.copy()
            try:
                yield
            except Exception:
                self.receipts = previous
                raise

        async def fetchval(self, sql, consumer, event_id, producer):
            assert 'INSERT INTO inbox' in sql and producer == 'auction'
            if event_id not in self.receipts:
                self.receipts.add(event_id)
                return event_id

        async def execute(self, sql, notice_id, event_id, recipient, kind, auction_id, listing_id,
                          sequence, current_minor, currency, ends_at, event_time, source_revision):
            assert 'INSERT INTO bid_notices' in sql
            assert auction_id == auction and recipient == bidder and sequence == lot['accepted_sequence']
            self.notices[kind] = dict(id=notice_id, event_id=event_id, listing_id=listing_id,
                current_minor=current_minor, currency=currency, source_revision=source_revision)

        async def fetchrow(self, sql, auction_id, sequence, recipient):
            assert 'JOIN bid_notices' in sql
            assert (auction_id, sequence, recipient) == (auction, lot['accepted_sequence'], bidder)
            return self.notices.get('outbid')

    app.state.pool = Store()

    def headers(source, audience='communications'):
        now = int(time.time())
        token = jwt.encode({'sub': source, 'type': 'service', 'iss': settings.auth_issuer,
                            'aud': audience, 'iat': now, 'exp': now + 60}, key, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token}

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        route = '/internal/v1/events'
        body = newer.model_dump(mode='json')
        auth = headers('auction')
        assert (await client.post(route, json=body, headers=auth)).status_code == 503
        assert (await client.post(route, json=accepted.model_dump(mode='json'), headers=auth)).json() == {'accepted': True}
        assert (await client.post(route, json=body, headers=auth)).json() == {'accepted': True}
        assert (await client.post(route, json=body, headers=auth)).json() == {'accepted': False}
        assert (await client.post(route, json={**body, 'type': 'auction.outbid.v2'}, headers=auth)).status_code == 403
        wrong_source = await client.post(route, json={**body, 'source': 'orders'}, headers=headers('orders'))
        assert wrong_source.status_code == 403
        wrong_revision = newer.model_copy(update={'id': uuid4(), 'data': {**facts, 'revision': lot['revision'] + 1}})
        assert (await client.post(route, json=wrong_revision.model_dump(mode='json'), headers=auth)).status_code == 422
        assert app.state.pool.notices['outbid']['event_id'] == accepted.id
        assert app.state.pool.notices['outbid']['source_revision'] == lot['revision']
        assert set(app.state.pool.notices) == {'bid_accepted', 'outbid'}


    timing_app = create_app(settings.model_copy(update={'service_name': 'auction'}))
    rules = next(module for module in discover(root / 'services/auction/modules') if module.id == 'L05.a-rules')
    timing_app.include_router(rules.load('events.py:router'))

    class TimingStore(Store):
        async def fetchrow(self, sql, auction_id):
            assert 'FROM auction_lots' in sql and auction_id == auction
            return lot

    timing_app.state.pool = TimingStore()
    async with AsyncClient(transport=ASGITransport(app=timing_app), base_url='http://test') as client:
        body = timing.model_dump(mode='json')
        auth = headers('auction', 'auction')
        assert (await client.post(route, json=body, headers=auth)).json() == {'accepted': True}
        assert (await client.post(route, json={**body, 'type': 'auction.unknown.v2'}, headers=auth)).status_code == 403
        wrong_source = await client.post(route, json={**body, 'source': 'orders'}, headers=headers('orders', 'auction'))
        assert wrong_source.status_code == 403


async def submit_beaten_challenger(monkeypatch, root):
    # Keep the Auction producer imports separate from the Communications runtime.
    with monkeypatch.context() as patch:
        for name in tuple(sys.modules):
            if name == 'service_app' or name.startswith('service_app.'):
                patch.delitem(sys.modules, name)
        patch.syspath_prepend(str(root / 'services/auction/runtime'))
        try:
            from service_app.engine import AuctionEngine
            from service_app.proxy_v2 import calculate
        finally:
            for name in tuple(sys.modules):
                if name == 'service_app' or name.startswith('service_app.'):
                    sys.modules.pop(name)

    auction, listing, watch, seller, bidder, leader = (uuid4() for _ in range(6))
    now = datetime.now(timezone.utc)
    ends = now + timedelta(hours=1)
    lot = dict(id=auction, listing_id=listing, watch_id=watch, seller_id=seller,
               seller_organization_id=None, listing_revision=1, currency='USD', revision=7,
               mode='bidding', opening_minor=400, current_minor=500, accepted_sequence=2,
               leader_id=leader, increment_bands=[{'from_minor': 0, 'step_minor': 50}],
               starts_at=now - timedelta(minutes=1), ends_at=ends, scheduled_ends_at=ends,
               end_version=1, high_value_minor=10000, first_bid_confirmed=True)
    emitted = {}

    class BidStore:
        @asynccontextmanager
        async def acquire(self, **kwargs):
            yield self

        @asynccontextmanager
        async def transaction(self, **kwargs):
            yield

        async def fetchrow(self, sql, *args):
            if 'FROM auction_operations' in sql:
                return None
            if 'FROM auction_lots' in sql:
                return dict(lot)
            assert sql.startswith('UPDATE auction_lots')
            _, current, leader_id, sequence, ends_at, end_version = args
            lot.update(current_minor=current, leader_id=leader_id, accepted_sequence=sequence,
                       ends_at=ends_at, end_version=end_version, revision=lot['revision'] + 1)
            return dict(lot)

        async def fetchval(self, sql, *args):
            if 'FROM auction_publication_watermarks' in sql:
                return None
            assert 'clock_timestamp()' in sql
            return now

        async def fetch(self, sql, *args):
            assert 'FROM auction_maxima' in sql
            return [dict(bidder_id=leader, amount_minor=900, sequence=1, active=True)]

        async def execute(self, sql, *args):
            if sql.startswith('INSERT INTO outbox'):
                _, destination, envelope = args
                assert destination not in emitted
                emitted[destination] = EventEnvelope.model_validate(json.loads(envelope))
            else:
                assert sql.startswith(('SELECT pg_advisory_xact_lock', 'INSERT INTO auction_', 'UPDATE auction_maxima'))

    class Dependencies:
        async def principal(self, request):
            return CurrentPrincipal(actor=Actor(subject_id=bidder, session_id='test-session'), roles=['buyer'])

        async def listing(self, request, listing_id):
            return dict(id=str(listing_id), watch_id=str(watch), seller_id=str(seller),
                        revision=1, status='published')

        async def check_fence(self, request, lot):
            assert lot['first_bid_confirmed']

        async def fee(self, request, command, lot, principal, checked_at):
            return ends

    app = SimpleNamespace(state=SimpleNamespace(pool=BidStore(), hooks={'auction.proxy.v2': calculate}))
    request = SimpleNamespace(app=app, headers={'idempotency-key': 'test-beaten-bid'},
                              state=SimpleNamespace(request_id='test-bid'))
    command = BidCommand(amount_minor=600, expected_revision=7, fee_quote_id=uuid4())
    receipt = await AuctionEngine(Dependencies()).submit(request, auction, command)
    assert receipt['status'] == 'succeeded' and lot['leader_id'] == leader
    assert set(emitted) == {'communications', 'bid-notices-v2', 'auction-timing-v2'}
    return auction, bidder, lot, emitted
