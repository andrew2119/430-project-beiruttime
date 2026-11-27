import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI
from bt_contracts_core.models import EventEnvelope
from bt_contracts_core.errors import PublicError
from bt_runtime.modules import discover
from pydantic import ValidationError
from bt_contracts.comms.inbox.v2 import PaymentNoticeReceiptV3
from bt_contracts.comms.bid_notices.v2 import OutbidV2

ROOT = Path(__file__).resolve().parents[4]
MODULES = {module.id: module for module in discover(ROOT / 'services/communications/modules')}
receive = MODULES['L07.inbox'].load('events.py:receive')
lookup = MODULES['L07.inbox'].load('events.py:lookup')
accepted = MODULES['L05.bid-notices'].load('events.py:accepted')
tick = MODULES['L07.inbox'].load('receipts.py:tick')


class Store:
    """Transactional query-boundary double; database behavior is separately owed."""
    def __init__(self):
        self.events, self.intents, self.notices, self.deliveries = {}, {}, [], []
        self.bids = []
        self.schema_ready = True
        self.optional_enabled = False
        self.now = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
        self.fail_intent = False
        self.lock = asyncio.Lock()

    async def fetchval(self, sql, *args):
        if 'to_regclass' in sql:
            return self.schema_ready
        if 'request_hash' in sql:
            return self.events.get(args[0])
        if 'clock_timestamp' in sql:
            return self.now
        if 'optional_enabled' in sql:
            return self.optional_enabled
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if 'WHERE order_id' in sql:
            return next((r for r in self.intents.values() if r['order_id'] == args[0]), None)
        if 'WHERE event_id' in sql:
            return self.intents.get(args[0])
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if 'INSERT INTO l07_notices' in sql:
            self.notices.append(args)
        elif 'INSERT INTO l22_notice_events' in sql:
            self.events[args[0]] = args[1]
        elif 'INSERT INTO l22_verified_notice_deliveries' in sql:
            self.deliveries.append(args)
        elif 'INSERT INTO l22_payment_notice_intents' in sql:
            if self.fail_intent:
                raise RuntimeError('storage unavailable')
            keys = ['event_id', 'notice_id', 'order_id', 'buyer_id', 'source_revision', 'notified_at', 'receipt']
            self.intents[args[0]] = dict(zip(keys, args)) | {'acknowledged_at': None, 'attempts': 0}
        elif 'UPDATE l22_payment_notice_intents' in sql:
            row = self.intents[args[0]]
            if row['lease_token'] == args[1]:
                if 'acknowledged_at=now()' in sql:
                    row['acknowledged_at'] = self.now
                row['lease_token'] = None
        elif 'INSERT INTO bid_notices' in sql:
            self.bids.append(args)
        else:
            raise AssertionError(sql)

    async def fetch(self, sql, *args):
        assert 'WITH due' in sql
        rows = []
        for row in self.intents.values():
            if row['acknowledged_at'] is None:
                row['lease_token'] = args[0]
                row['attempts'] += 1
                rows.append(dict(row))
        return rows

    @asynccontextmanager
    async def acquire(self, **kwargs):
        yield self


@asynccontextmanager
async def transaction(pool, **kwargs):
    async with pool.lock:
        snapshot = deepcopy((pool.events, pool.intents, pool.notices, pool.deliveries))
        try:
            yield pool
        except Exception:
            pool.events, pool.intents, pool.notices, pool.deliveries = snapshot
            raise


@pytest.fixture
def setup(monkeypatch):
    import sys
    monkeypatch.setattr(sys.modules[receive.__module__], 'unit_of_work', transaction)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    pool = Store()
    settings = SimpleNamespace(service_auth_public_key=public, auth_issuer='beirut-time-identity')
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool, settings=settings)), headers={})

    def authorize(source='orders', **patch):
        now = int(datetime.now(timezone.utc).timestamp())
        claims = {'sub': source, 'type': 'service', 'aud': 'communications', 'iss': settings.auth_issuer,
                  'iat': now, 'exp': now+60, **patch}
        request.headers = {'Authorization': 'Bearer '+jwt.encode(claims, key, algorithm='RS256')}
        return request
    return pool, request, authorize


def payment():
    fixture = json.loads((ROOT / 'packages/contracts-comms/inbox/fixtures-v2.json').read_text())
    return EventEnvelope.model_validate(fixture['success']['event'])


def run(awaitable):
    return asyncio.run(awaitable)


def test_duplicate_and_reordered_events_keep_each_order_clock(setup):
    pool, request, auth = setup
    first = run(receive(payment(), auth()))
    original = first['receipt']
    pool.now += timedelta(hours=5)
    other = payment().model_copy(update={'id': uuid4(), 'subject': str(uuid4())})
    other = other.model_copy(update={'data': {**other.data, 'order_id': other.subject, 'buyer_id': str(uuid4())}})
    second = run(receive(other, auth()))
    replay = run(receive(payment(), auth()))
    assert replay == {'accepted': False, 'receipt': original}
    assert second['receipt']['notified_at'] != original['notified_at']
    assert len(pool.notices) == len(pool.intents) == len(pool.deliveries) == 2
    assert run(lookup(payment().id, auth('communications'))) == {'receipt': original, 'state': 'pending'}
    assert request.app.state.pool.optional_enabled is False


@pytest.mark.parametrize('change', ['buyer', 'event', 'revision', 'time'])
def test_conflicting_replay_denies_without_changing_original(setup, change):
    pool, _, auth = setup
    event = payment()
    run(receive(event, auth()))
    if change == 'event':
        event = event.model_copy(update={'id': uuid4()})
    elif change == 'time':
        event = event.model_copy(update={'time': pool.now+timedelta(hours=1)})
    else:
        event = event.model_copy(update={'data': {**event.data, **({'buyer_id': str(uuid4())} if change == 'buyer' else {'revision': 2})}})
    with pytest.raises(PublicError):
        run(receive(event, auth()))
    assert len(pool.notices) == len(pool.intents) == len(pool.events) == 1


def test_intent_failure_rolls_back_notice_and_verified_record(setup):
    pool, _, auth = setup
    pool.fail_intent = True
    with pytest.raises(RuntimeError):
        run(receive(payment(), auth()))
    assert not pool.notices and not pool.intents and not pool.deliveries and not pool.events
    pool.fail_intent = False
    assert run(receive(payment(), auth()))['accepted'] is True


@pytest.mark.parametrize('patch', [{'sub': 'pricing'}, {'type': 'access'}, {'aud': 'orders'}, {'exp': 1}])
def test_denied_producer_commits_nothing(setup, patch):
    from fastapi import HTTPException
    pool, _, auth = setup
    with pytest.raises(HTTPException):
        run(receive(payment(), auth(**patch)))
    assert not pool.notices and not pool.intents


@pytest.mark.parametrize('status,body', [(503, {}), (403, {}), (200, {}), (200, {'notified_at': 'wrong'})])
def test_refused_or_malformed_delivery_preserves_exact_intent(setup, status, body):
    pool, _, auth = setup
    original = run(receive(payment(), auth()))['receipt']
    sent = []
    class Orders:
        async def request(self, method, path, **kwargs):
            sent.append(kwargs['json'])
            assert method == 'POST' and path == '/internal/v3/payment-notices'
            return httpx.Response(status, json=body)
    run(tick(pool, Orders(), lambda: {}))
    assert sent == [original]
    assert pool.intents[payment().id]['acknowledged_at'] is None


def test_lost_response_retries_original_receipt_then_acknowledges(setup):
    from bt_bulkheads import Unavailable
    pool, _, auth = setup
    original = run(receive(payment(), auth()))['receipt']
    sent = []
    class Orders:
        async def request(self, method, path, **kwargs):
            sent.append(deepcopy(kwargs['json']))
            if len(sent) == 1:
                return Unavailable('orders', 'timeout')
            return httpx.Response(200, json=original)
    orders = Orders()
    run(tick(pool, orders, lambda: {}))
    pool.now += timedelta(hours=1)
    run(tick(pool, orders, lambda: {}))
    assert sent == [original, original]
    assert pool.intents[payment().id]['acknowledged_at'] == pool.now
    assert run(lookup(payment().id, auth('communications')))['receipt'] == original


def test_displaced_and_immediately_beaten_recipients_are_separate(setup):
    pool, _, _ = setup
    holder, challenger, leader = uuid4(), uuid4(), uuid4()
    event = EventEnvelope(type='auction.bid-accepted.v1', source='auction', subject=str(uuid4()), request_id='bid', data={})
    event = event.model_copy(update={'data': {'auction_id': event.subject, 'listing_id': str(uuid4()),
        'sequence': 7, 'revision': 8, 'current_minor': 430000, 'currency': 'USD', 'ends_at': pool.now.isoformat(),
        'bidder_id': str(challenger), 'previous_leader_id': str(holder), 'leader_id': str(leader)}})
    run(accepted(pool, event))
    outbid = [r for r in pool.bids if r[3] == 'outbid']
    assert {r[2] for r in outbid} == {holder, challenger}
    assert len(outbid) == 2
    assert all(len(row) == 12 and row[-1] == 8 for row in pool.bids)


def test_outbid_v2_is_required_and_rejects_private_fields(setup):
    pool, _, auth = setup
    data = json.loads((ROOT / 'packages/contracts-comms/bid-notices/fixtures-v2.json').read_text())['success']
    event = EventEnvelope(type='auction.outbid.v2', source='auction', subject=data['auction_id'], request_id='outbid', data=data)
    assert run(receive(event, auth('auction')))['accepted'] is True
    assert run(receive(event, auth('auction')))['accepted'] is False
    assert len(pool.notices) == 1 and pool.notices[0][-2] is True
    with pytest.raises(ValidationError):
        OutbidV2.model_validate({**data, 'maxima': []})


def test_receipt_schema_is_exact():
    receipt = json.loads((ROOT / 'packages/contracts-comms/inbox/fixtures-v2.json').read_text())['success']['receipt']
    assert PaymentNoticeReceiptV3.model_validate(receipt).buyer_id == UUID(receipt['buyer_id'])
    with pytest.raises(ValidationError):
        PaymentNoticeReceiptV3.model_validate({**receipt, 'ceiling': 450000})


def test_registration_loads_both_receivers_before_delivery():
    module = MODULES['L07.inbox']
    router = module.load('events.py:router')
    paths = {route.path for route in router.routes}
    assert {'/internal/v1/inbox/events', '/internal/v2/inbox/events'} <= paths
    assert not module.workers
    app = FastAPI()
    app.include_router(router)
    assert len(app.routes) >= 7


@pytest.mark.parametrize('flag', [None, False, 1, 'true'])
def test_receipt_requires_explicit_boolean_verification(flag):
    receipt = json.loads((ROOT / 'packages/contracts-comms/inbox/fixtures-v2.json').read_text())['success']['receipt']
    with pytest.raises(ValidationError):
        PaymentNoticeReceiptV3.model_validate({**receipt, 'verified_delivery_recorded': flag})
    receipt.pop('verified_delivery_recorded')
    with pytest.raises(ValidationError):
        PaymentNoticeReceiptV3.model_validate(receipt)


def test_quote_v3_opt_out_and_payment_subject_binding(setup):
    pool, _, auth = setup
    event = payment()
    quote = EventEnvelope(type='pricing.quote-created.v3', source='pricing', subject=str(uuid4()), request_id='quote', data={})
    quote = quote.model_copy(update={'data': {'occurrence_id': str(quote.id), 'recipient_id': event.data['buyer_id'],
        'kind': 'quote_ready', 'resource_id': quote.subject, 'resource_owner_id': event.data['buyer_id'],
        'resource_revision': 1, 'event_time': pool.now.isoformat(), 'sample': True}})
    assert run(receive(quote, auth('pricing')))['accepted'] is True
    assert not pool.notices
    with pytest.raises(PublicError):
        run(receive(event.model_copy(update={'subject': str(uuid4())}), auth()))
    assert not pool.intents
    assert run(receive(event, auth()))['accepted'] is True


def test_receipt_is_not_acknowledged_for_another_order(setup):
    pool, _, auth = setup
    original = run(receive(payment(), auth()))['receipt']
    class Orders:
        async def request(self, method, path, **kwargs):
            return httpx.Response(200, json={**original, 'order_id': str(uuid4())})
    run(tick(pool, Orders(), lambda: {}))
    assert pool.intents[payment().id]['acknowledged_at'] is None


def test_simultaneous_duplicates_commit_one_notice(setup):
    pool, _, auth = setup
    async def deliver():
        request = auth()
        return await asyncio.gather(receive(payment(), request), receive(payment(), request))
    results = run(deliver())
    assert sorted(r['accepted'] for r in results) == [False, True]
    assert results[0]['receipt'] == results[1]['receipt']
    assert len(pool.notices) == len(pool.intents) == len(pool.deliveries) == 1


def test_http_receivers_and_lookup_use_authenticated_contract(setup):
    pool, request, auth = setup
    app = FastAPI()
    app.state.pool = pool
    app.state.settings = request.app.state.settings
    app.include_router(MODULES['L07.inbox'].load('events.py:router'))
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://communications') as client:
            body = payment().model_dump(mode='json')
            denied = await client.post('/internal/v2/inbox/events', json=body)
            assert denied.status_code == 401 and not pool.intents
            first = await client.post('/internal/v2/inbox/events', json=body, headers=auth().headers)
            assert first.status_code == 200
            replay = await client.post('/internal/v1/inbox/events', json=body, headers=auth().headers)
            assert replay.json()['receipt'] == first.json()['receipt']
            found = await client.get('/internal/v2/inbox/payment-notices/'+body['id'], headers=auth('communications').headers)
            assert found.status_code == 200 and found.json()['receipt'] == first.json()['receipt']
            denied_lookup = await client.get('/internal/v2/inbox/payment-notices/'+body['id'], headers=auth('orders').headers)
            assert denied_lookup.status_code == 403
    run(exercise())


def test_success_fixture_uses_the_same_notice_identity(setup):
    from uuid import NAMESPACE_URL, uuid5
    fixture = json.loads((ROOT / 'packages/contracts-comms/inbox/fixtures-v2.json').read_text())
    event, receipt = fixture['success']['event'], fixture['success']['receipt']
    assert receipt['notice_id'] == str(uuid5(NAMESPACE_URL,
        f"payment-notice:{event['id']}:{event['data']['buyer_id']}:{event['data']['order_id']}"))


def test_preference_lost_response_returns_original_result_and_conflicts_deny(monkeypatch):
    import sys
    from bt_contracts.comms.inbox.models import Preferences
    save = MODULES['L07.inbox'].load('routes.py:save_preferences')
    monkeypatch.setattr(sys.modules[save.__module__], 'unit_of_work', transaction)
    class PreferenceStore(Store):
        def __init__(self):
            super().__init__()
            self.operations, self.preferences = {}, {}
        async def fetchrow(self, sql, *args):
            assert 'l07_notice_operations' in sql
            return self.operations.get(tuple(args))
        async def fetchval(self, sql, *args):
            assert 'SELECT revision' in sql
            return self.preferences.get(args[0], {}).get('revision')
        async def execute(self, sql, *args):
            if 'INSERT INTO l07_notice_operations' in sql:
                self.operations[tuple(args[:2])] = {'request_hash': args[2], 'result': args[3]}
            elif 'INSERT INTO l07_notice_preferences' in sql:
                prior = self.preferences.get(args[0], {'revision': 0})
                self.preferences[args[0]] = {'revision': prior['revision']+1, 'optional_enabled': args[1]}
            else:
                raise AssertionError(sql)
    pool, owner = PreferenceStore(), uuid4()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
    body = Preferences(optional_enabled=False, expected_revision=0)
    original = run(save(body, request, owner, 'preference-one'))
    assert run(save(body, request, owner, 'preference-one')) == original
    assert pool.preferences[owner] == {'optional_enabled': False, 'revision': 1}
    with pytest.raises(PublicError):
        run(save(Preferences(optional_enabled=True, expected_revision=0), request, owner, 'preference-one'))
    other = uuid4()
    assert run(save(body, request, other, 'preference-one')) == original
    assert len(pool.operations) == 2


def test_receipt_migration_has_its_own_lane_registration():
    assert 'L22.notice-receipts' not in MODULES
    registration = json.loads((ROOT / 'services/communications/modules/inbox/notice-receipts/deferred-registration.json').read_text())
    assert registration['migrations'] == ['migrations/L22_0022_notice_receipts.sql']
    assert all(path.name.startswith('L07_') for path in MODULES['L07.inbox'].migrations)


def test_missing_receipt_schema_refuses_new_events_without_writes(setup):
    from fastapi import HTTPException
    pool, _, auth = setup
    pool.schema_ready = False
    with pytest.raises(HTTPException) as denied:
        run(receive(payment(), auth()))
    assert denied.value.status_code == 503
    with pytest.raises(HTTPException) as missing:
        run(lookup(payment().id, auth('communications')))
    assert missing.value.status_code == 503
    class Orders:
        async def request(self, *args, **kwargs):
            raise AssertionError('No delivery before schema activation')
    run(tick(pool, Orders(), lambda: {}))
    assert not pool.events and not pool.notices and not pool.intents and not pool.deliveries


def test_missing_receipt_schema_preserves_existing_receiver(setup):
    pool, request, auth = setup
    class LegacyStore(Store):
        def __init__(self):
            super().__init__()
            self.schema_ready = False
            self.received = set()
        async def fetchval(self, sql, *args):
            if 'INSERT INTO inbox ' in sql:
                key = args[:2]
                if key in self.received:
                    return None
                self.received.add(key)
                return args[1]
            return await super().fetchval(sql, *args)
    legacy = LegacyStore()
    request.app.state.pool = legacy
    event = payment().model_copy(update={'type': 'pricing.quote-reviewed.v1', 'source': 'pricing'})
    assert run(receive(event, auth('pricing'))) == {'accepted': True}
    assert run(receive(event, auth('pricing'))) == {'accepted': False}
    assert legacy.received == {('L07.inbox', event.id)}
    assert not legacy.events and not legacy.intents
