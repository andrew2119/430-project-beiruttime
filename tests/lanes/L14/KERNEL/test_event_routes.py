from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
import jwt
import pytest

from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import Actor
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from bt_runtime.principal import CurrentPrincipal
from conftest import ROOT, load


class Store:
    def __init__(self):
        self.outbox = {}
        self.rows = {}
        self.watermark = None
        self.lot = None
        self.edit = None

    @asynccontextmanager
    async def acquire(self, **kwargs):
        yield self

    @asynccontextmanager
    async def transaction(self, **kwargs):
        yield

    async def fetchval(self, sql, *args):
        if 'FROM auction_publication_watermarks' in sql:
            return self.watermark[1] if self.watermark else None
        if 'INSERT INTO inbox' in sql:
            consumer, event_id, _ = args
            assert consumer == 'auction.current-state'
            return event_id
        assert 'SELECT id FROM l02_memberships' in sql
        return None

    async def execute(self, sql, *args):
        if sql.startswith('INSERT INTO outbox'):
            _, destination, envelope = args
            body = json.loads(envelope)
            self.outbox[body['type'], destination] = body
        elif sql.startswith('INSERT INTO auction_publication_watermarks'):
            self.watermark = args
        elif "SET state='aborted'" in sql:
            self.edit['state'] = 'aborted'

    async def fetchrow(self, sql, *args):
        if 'FROM auction_listing_edits' in sql:
            return self.edit
        if 'FROM auction_lots' in sql:
            return self.lot
        if sql.startswith('UPDATE auction_lots'):
            self.lot.update(revision=self.lot['revision'] + 1, mode='bidding')
            if 'SET listing_revision=' in sql:
                self.lot['listing_revision'] = args[1]
            return self.lot
        for query, row in self.rows.items():
            if query in sql:
                return row
        assert '_operations' in sql
        return None


def request_for(store, **state):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=store, **state)),
                           state=SimpleNamespace(request_id='test-event'))


async def publish(store, listing, seller):
    repository = load('catalog_listing_repository', 'services/catalog/runtime/service_app/listing_repository.py')
    await repository.emit(store, request_for(store), dict(id=listing, revision=2, owner_subject_id=seller,
                          organization_id=None, status='published', is_demo=False, facts={'sale_mode': 'auction'}),
                          'published')


async def identity_events(store, monkeypatch):
    now = datetime.now(timezone.utc)
    actor_id, business, member, challenge = (uuid4() for _ in range(4))
    actor = CurrentPrincipal(actor=Actor(subject_id=actor_id, session_id='test-session'),
                             permissions=['identity.businesses.manage', 'identity.membership.manage'])
    request = request_for(store)

    async def no_op(*args, **kwargs):
        pass

    async def subjects(*args):
        return []

    async def live_actor(*args, **kwargs):
        return {'id': actor_id}, None

    with monkeypatch.context() as patch:
        for name in tuple(sys.modules):
            if name == 'service_app' or name.startswith('service_app.'):
                patch.delitem(sys.modules, name)
        patch.syspath_prepend(str(ROOT / 'services/identity/runtime'))
        from service_app import identity

        patch.setattr(identity, 'lock_accounts', no_op)
        patch.setattr(identity, 'live_actor', live_actor)
        modules = {module.root.name: module for module in discover(ROOT / 'services/identity/modules')}
        change = modules['businesses'].load('routes.py:change')
        grant = modules['membership'].load('routes.py:grant')
        verify = modules['contacts'].load('routes.py:verify')
        for command, names in (
            (change, {'affected_subjects': subjects, 'require_current': no_op, 'sync_business': no_op}),
            (grant, {'require_current': no_op, 'sync_member': no_op}),
            (verify, {'live_actor': live_actor}),
        ):
            for name, replacement in names.items():
                patch.setitem(command.__globals__, name, replacement)

        active = dict(id=business, public_name='Example dealer', kind='dealer', capabilities=['sales'],
                      state='active', revision=1, sample=False)
        store.rows = {
            'FROM l02_businesses': active,
            'UPDATE l02_businesses': {**active, 'state': 'revoked', 'revision': 2},
            'INSERT INTO l02_memberships': dict(id=uuid4(), business_id=business, subject_id=member,
                capabilities=['business.stock.write'], qualifications=[], intervention_scope='Example scope',
                state='active', revision=1),
            'FROM l02_contact_challenges': dict(consumed_at=None, expires_at=now + timedelta(minutes=5),
                attempts=0, contact_revision=0, code_digest=verify.__globals__['digest'](challenge, '123456'),
                channel='phone', recipient='+12025550101', simulated_code=None),
            'FROM l02_contacts': None,
            'UPDATE l02_contacts': dict(revision=2, email=None, phone='+12025550101', email_verified_at=None,
                phone_verified_at=now, email_sample=False, phone_sample=False),
        }
        try:
            await grant(grant.__globals__['Grant'](business_id=business, subject_id=member,
                capabilities=['business.stock.write'], intervention_scope='Example scope', reason='Example grant'),
                request, actor, 'test-membership')
            await change(business, change.__globals__['Change'](state='revoked', revision=1, reason='Example revocation'),
                         request, actor, 'test-business')
            await verify(challenge, verify.__globals__['Proof'](code='123456'), request, actor, 'test-contact')
        finally:
            for name in tuple(sys.modules):
                if name == 'service_app' or name.startswith('service_app.'):
                    sys.modules.pop(name)


async def edit_event(store, modules, kind, listing, seller):
    auction, watch, operation = (uuid4() for _ in range(3))
    now = datetime.now(timezone.utc)
    facts = {'sale_mode': 'auction'}
    publication = dict(id=str(listing), physical_watch_id=str(watch), seller_id=str(seller),
                       status='published', revision=3, facts=facts)
    store.lot = dict(id=auction, listing_id=listing, revision=3, end_version=2, listing_revision=2,
                     mode='listing_edit_pending', accepted_sequence=0, first_bid_confirmed=False,
                     seller_id=seller, seller_organization_id=None)
    store.edit = dict(operation_id=operation, listing_id=listing, watch_id=watch, listing_revision=2,
                      auction_id=auction, state='prepared', next_revision=3,
                      facts_digest=hashlib.sha256(json.dumps(facts, separators=(',', ':')).encode()).hexdigest(),
                      protocol=3, dispatched_at=None, expires_at=now, refence_command=None)
    edits = modules['L14.b-listing-edits']
    if kind == 'auction.listing-edit-aborted.v3':
        abort = edits.load('recovery.py:abort_locked')
        await abort(store, request_for(store), store.edit, 'prepare_expired', now)
    else:
        class Dependencies:
            def service_headers(self, request, audience):
                return {}

            async def json(self, peer, method, path, request, **kwargs):
                if peer == 'catalog':
                    return publication
                assert peer == 'orders'
                return dict(watch_id=str(watch), listing_id=str(listing), revision=5, listing_revision=3,
                            auction_committed=False, status='fenced', source_id=str(auction))

        store.edit['dispatched_at'] = now
        commit = edits.load('routes.py:commit_intent')
        body = commit.__globals__['CommitListingEdit'](listing_revision=3)
        await commit(operation, body, request_for(store, auction=SimpleNamespace(dependencies=Dependencies())))


@pytest.mark.parametrize('kind,destination,source', [
    ('catalog.listing.published.v1', 'auction', 'catalog'),
    ('identity.business-status-changed.v1', 'auction', 'identity'),
    ('identity.membership-changed.v1', 'auction', 'identity'),
    ('identity.contact-verified.v1', 'auction', 'identity'),
    ('auction.listing-revised.v2', 'auction-timing-v2', 'auction'),
    ('auction.listing-edit-aborted.v3', 'auction-timing-v2', 'auction'),
])
@pytest.mark.asyncio
async def test_invalidation_contract(kind, destination, source, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'services/auction/runtime'))
    modules = {module.id: module for module in discover(ROOT / 'services/auction/modules')}
    store = Store()
    listing, seller = uuid4(), uuid4()
    if source == 'catalog':
        await publish(store, listing, seller)
    elif source == 'identity':
        await identity_events(store, monkeypatch)
    else:
        await edit_event(store, modules, kind, listing, seller)
    body = store.outbox[kind, destination]

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    settings = Settings(database_url='postgresql://unused/unused', modules_path=tmp_path,
                        service_name='auction', service_auth_public_key=public)
    app = create_app(settings)
    app.include_router(modules['L05.a-rules'].load('events.py:router'))
    app.state.pool = store

    def headers(producer):
        now = int(time.time())
        token = jwt.encode({'sub': producer, 'type': 'service', 'iss': settings.auth_issuer,
                            'aud': 'auction', 'iat': now, 'exp': now + 60}, key, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token}

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        route = '/internal/v1/events'
        assert (await client.post(route, json=body, headers=headers(source))).json() == {'accepted': True}
        unknown = await client.post(route, json={**body, 'type': 'test.unknown.v1'}, headers=headers(source))
        wrong_source = await client.post(route, json={**body, 'source': 'orders'}, headers=headers('orders'))
        assert unknown.status_code == wrong_source.status_code == 403
        wrong_subject = await client.post(route, json={**body, 'subject': str(uuid4())}, headers=headers(source))
        assert wrong_subject.status_code == 422
        if source == 'catalog':
            assert store.watermark == (listing, 2)
            from service_app.engine import AuctionEngine

            with pytest.raises(PublicError, match='listing_changed'):
                await AuctionEngine.require_current_publication(store, listing, 1)
            await AuctionEngine.require_current_publication(store, listing, 2)
