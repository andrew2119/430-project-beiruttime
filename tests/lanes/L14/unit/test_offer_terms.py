import asyncio
import importlib
import sys
import types
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import UUID
import pytest
from conftest import ROOT, load
from bt_contracts.pricing.offers.models import MakeOffer, AnswerOffer
from bt_contracts_core.errors import PublicError
from bt_runtime.principal import CurrentPrincipal

# This module can run alone, without loading another unit module first.
for name, relative in [('service_app', 'services/pricing/runtime/service_app'), ('l14offers', 'services/pricing/modules/offers')]:
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(ROOT / relative)]
        sys.modules[name] = package
routes = load('l14offers.routes', 'services/pricing/modules/offers/routes.py')
closure = load('l14offers.closure', 'services/pricing/modules/offers/closure.py')
peers = importlib.import_module('service_app.peers')
BUYER, SELLER, LISTING, WATCH, QUOTE, OFFER = (UUID(int=i) for i in range(20, 26))
NOW = datetime.now(timezone.utc)


def row():
    return {'id': OFFER, 'listing_id': LISTING, 'listing_revision': 1, 'watch_id': WATCH, 'quote_id': QUOTE,
            'seller_id': SELLER, 'seller_organization_id': None, 'buyer_id': BUYER, 'state': 'open', 'revision': 1,
            'orders_result': None, 'expires_at': NOW + timedelta(hours=48),
            'snapshot': {'id': str(QUOTE), 'subject_id': str(LISTING), 'subject_revision': 1, 'purpose': 'offer',
                         'price_minor': 500000, 'payable_minor': 515000, 'revision': 1, 'currency': 'USD',
                         'schedule_id': 'usd-v2', 'policy': {'revision': 2},
                         'expires_at': (NOW - timedelta(minutes=1)).isoformat()}}


class DB:
    def __init__(self):
        self.offer = row()
        self.executed = []
        self.result = {}
    async def fetchrow(self, sql, *args):
        self.executed.append((sql, args))
        if 'FROM l07_quotes' in sql:
            return {'snapshot': self.offer['snapshot'], 'reviewed_at': NOW-timedelta(minutes=1),
                    'expires_at': NOW+timedelta(minutes=14)}
        if 'INSERT INTO l14_offers' in sql:
            self.offer['expires_at'] = args[-1]
        if 'UPDATE l14_offers' in sql and 'acceptance_pending' in sql:
            self.offer['state'] = 'acceptance_pending'
        return self.offer
    async def fetchval(self, sql, *args):
        if 'clock_timestamp' in sql:
            return NOW
        if 'SELECT result' in sql:
            return self.result
        return False
    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        if 'SET result=$2' in sql:
            self.result = args[1]
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


def setup(monkeypatch):
    db = DB()
    @asynccontextmanager
    async def uow(*args, **kwargs):
        yield db
    async def replay(*args):
        return None
    async def remember(*args):
        return {'operation_id': str(UUID(int=100)), **args[-1]}
    async def notice(*args):
        pass
    async def call(*args, **kwargs):
        return {'watch_id': str(WATCH), 'listing_id': str(LISTING), 'listing_revision': 1, 'status': 'available', 'revision': 1}
    monkeypatch.setattr(routes, 'unit_of_work', uow)
    monkeypatch.setattr(routes, 'replay', replay)
    monkeypatch.setattr(routes, 'remember', remember)
    monkeypatch.setattr(routes, 'notice', notice)
    monkeypatch.setattr(peers, 'call', call)
    async def listing(*args):
        return {'id': str(LISTING), 'seller_id': str(SELLER), 'organization_id': None,
                'physical_watch_id': str(WATCH), 'facts': {'currency': 'USD', 'sale_mode': 'offer'}}
    monkeypatch.setattr(peers, 'listing', listing)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=lambda: db))))
    return db, request


def test_sent_lifetime_is_48_hours_not_preview_lifetime(monkeypatch):
    db, request = setup(monkeypatch)
    principal = CurrentPrincipal(actor={'subject_id': BUYER, 'session_id': 'unit'}, roles=['buyer'])
    body = MakeOffer(listing_id=LISTING, listing_revision=1, amount_minor=500000,
                     currency='USD', schedule_id='usd-v2', fee_quote_id=QUOTE)
    result = asyncio.run(routes.make(body, request, principal, 'unit-make-offer'))
    assert result['offer']['state'] == 'open'
    assert db.offer['expires_at'] == NOW + timedelta(hours=48)
    assert 'expires_at' not in MakeOffer.model_fields


def test_acceptance_near_deadline_ignores_old_preview_expiry(monkeypatch):
    db, request = setup(monkeypatch)
    db.offer['expires_at'] = NOW + timedelta(seconds=1)
    principal = CurrentPrincipal(actor={'subject_id': SELLER, 'session_id': 'unit'}, roles=['private_seller'],
                                 permissions=['identity.listings.publish'])
    async def reconcile(*args):
        pass
    monkeypatch.setattr(routes, 'reconcile', reconcile)
    result = asyncio.run(routes.answer(OFFER, AnswerOffer(expected_revision=1, action='accept'), request, principal, 'unit-accept'))
    assert routes.decoded(result)['status'] == 'pending'
    assert db.offer['state'] == 'acceptance_pending'
    assert any('accepted_at=clock_timestamp()' in sql for sql, _ in db.executed)


@pytest.mark.parametrize('side', ['buyer', 'seller'])
def test_own_unblock_does_not_remove_other_partys_block(monkeypatch, side):
    db, request = setup(monkeypatch)
    who = BUYER if side == 'buyer' else SELLER
    principal = CurrentPrincipal(actor={'subject_id': who, 'session_id': 'unit'}, roles=['buyer', 'private_seller'],
                                 permissions=['identity.listings.publish'])
    asyncio.run(routes.set_block(OFFER, request, principal, 'own-unblock', remove=True))
    sql, args = next((sql, args) for sql,args in db.executed if sql.startswith('DELETE'))
    assert 'blocker_scope=$3' in sql and args == (str(SELLER), BUYER, str(who))


@pytest.mark.parametrize('mode,allowed', [('fixed_price', True), ('offer', True), ('auction', False)])
def test_listing_modes_and_currency_admission(monkeypatch, mode, allowed):
    async def call(*args, **kwargs):
        return {'id': str(LISTING), 'revision': 1, 'status': 'published', 'physical_watch_id': str(WATCH),
                'seller_id': str(SELLER), 'facts': {'sale_mode': mode, 'currency': 'USD'}}
    monkeypatch.setattr(peers, 'call', call)
    if allowed:
        assert asyncio.run(peers.listing(None, LISTING, 1))['facts']['sale_mode'] == mode
    else:
        with pytest.raises(PublicError):
            asyncio.run(peers.listing(None, LISTING, 1))


def test_cross_route_closure_requires_authoritative_matching_commitment():
    watch = {'watch_id': str(WATCH), 'listing_id': str(LISTING), 'listing_revision': 1, 'status': 'reserved'}
    assert closure.committed(watch, row())
    assert closure.committed({**watch, 'status': 'withdrawn'}, row())
    for bad in [{'status': 'available'}, {'status': 'unknown'}, {'status': 'fenced'}, {'watch_id': str(UUID(int=99))}]:
        assert not closure.committed({**watch, **bad}, row())
