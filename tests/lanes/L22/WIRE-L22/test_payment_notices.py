"""Contract-identical local persistence and delivery failures, without a database."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from bt_bulkheads import Unavailable
from bt_contracts_core.models import EventEnvelope
from service_app import payment_notices as notices

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
BUYER = UUID('00000000-0000-0000-0000-000000000001')
ORDER = UUID('00000000-0000-0000-0000-000000000002')
EVENT = UUID('00000000-0000-0000-0000-000000000003')


def event(**changes):
    data = {'order_id': str(ORDER), 'buyer_id': str(BUYER), 'recipient_id': str(BUYER),
        'revision': 2, 'required': True, 'sample': False, 'simulated': True}
    data.update(changes)
    return EventEnvelope(id=EVENT, type='orders.payment-action-required.v3', source='orders',
        subject=str(ORDER), time=NOW, request_id='notice-001', data=data)


class Store:
    def __init__(self):
        self.row = None
        self.writes = []
        self.committed = False

    async def execute(self, sql, *args):
        self.writes.append(sql)
        if 'INSERT INTO l22_payment_notices' in sql:
            self.row = dict(zip(('event_id', 'order_id', 'buyer_id', 'order_revision',
                'fingerprint', 'notice_id', 'notified_at'), args))
            self.row['verified_delivery_recorded'] = False

    async def fetchrow(self, sql, *args):
        return self.row

    async def fetchval(self, sql, *args):
        self.writes.append(sql)
        if 'INSERT INTO l07_notices' in sql:
            return NOW
        if 'UPDATE l22_payment_notices' in sql:
            self.row['verified_delivery_recorded'] = True
            self.row['contact_revision'], self.row['channel'], self.row['recipient_digest'] = args[2:]
            return args[0]
        raise AssertionError('Unexpected persistence operation')

    @asynccontextmanager
    async def transaction(self):
        original = deepcopy((self.row, self.writes))
        self.committed = False
        try:
            yield self
        except Exception:
            self.row, self.writes = original
            raise
        else:
            self.committed = True


@pytest.mark.asyncio
async def test_atomic_notice_receipt_and_conflicting_duplicates():
    store = Store()
    async with store.transaction():
        assert await notices.persist(store, event())
    assert store.committed
    assert sum('INSERT INTO l07_notices' in sql for sql in store.writes) == 1
    assert sum('INSERT INTO inbox' in sql for sql in store.writes) == 1
    async with store.transaction():
        assert not await notices.persist(store, event())
    assert store.row['order_revision'] == 2
    other_buyer = str(uuid4())
    for changed in (event(revision=1), event(buyer_id=other_buyer, recipient_id=other_buyer)):
        before = deepcopy(store.row)
        with pytest.raises(HTTPException) as exc:
            async with store.transaction():
                await notices.persist(store, changed)
        assert exc.value.status_code == 409
        assert store.row == before


@pytest.mark.asyncio
async def test_failure_rolls_back_inbox_and_notice():
    store = Store()
    original = store.execute

    async def fail(sql, *args):
        if 'INSERT INTO inbox' in sql:
            raise RuntimeError('Receipt write failed')
        await original(sql, *args)

    store.execute = fail
    with pytest.raises(RuntimeError):
        async with store.transaction():
            await notices.persist(store, event())
    assert store.row is None and store.writes == []


@pytest.mark.asyncio
async def test_malformed_and_mismatched_intent_stays_unpublished():
    for candidate, status in (
        (event(revision=0), 422), (event(revision=True), 422), (event(revision='2'), 422),
        (event(recipient_id=str(uuid4())), 422), (event(unknown=True), 422),
        (event(required=False), 422), (event(simulated=False), 422), (event(sample='false'), 422),
        (event(order_id=str(uuid4())), 409),
    ):
        store = Store()
        with pytest.raises(HTTPException) as exc:
            async with store.transaction():
                await notices.persist(store, candidate)
        assert exc.value.status_code == status
        assert store.row is None


class Client:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.callback(method, path, kwargs)


@pytest.mark.asyncio
async def test_recipient_commit_precedes_call_and_lost_response_reuses_receipt(monkeypatch):
    store = Store()
    async with store.transaction():
        await notices.persist(store, event())
    monkeypatch.setattr(notices, 'unit_of_work', lambda pool: store.transaction())
    monkeypatch.setattr(notices, 'headers', lambda *args: {'Authorization': 'Bearer synthetic'})
    identity = Client(lambda *args: httpx.Response(200, json={
        'subject_id': str(BUYER), 'revision': 4, 'email': 'buyer@example.invalid', 'email_sample': True}))

    def orders_result(*args):
        assert store.committed and store.row['verified_delivery_recorded']
        return Unavailable('orders', 'timeout')

    orders = Client(orders_result)
    app = SimpleNamespace(state=SimpleNamespace(identity=identity, orders=orders, pool=store))
    lease = uuid4()
    assert not await notices.deliver(app, dict(store.row), lease, '')
    orders.callback = lambda *args: httpx.Response(200, json={'status': 'succeeded',
        'order': {'id': str(ORDER), 'state': 'awaiting_payment'}})
    assert await notices.deliver(app, dict(store.row), lease, '')
    assert identity.calls[0][:2] == ('GET', f'/internal/v1/contacts/{BUYER}/delivery')
    assert orders.calls[0][:2] == ('POST', '/internal/v3/payment-notices')
    assert orders.calls[0][2]['json'] == orders.calls[1][2]['json'] == {
        'event_id': str(EVENT), 'notice_id': str(store.row['notice_id']),
        'order_id': str(ORDER), 'buyer_id': str(BUYER), 'notified_at': NOW.isoformat(),
        'verified_delivery_recorded': True,
    }
    assert len(identity.calls) == 1
    assert 'buyer@example.invalid' not in store.row.values()


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [Unavailable('identity', 'timeout'), httpx.Response(403),
    httpx.Response(200, json={'subject_id': str(BUYER), 'revision': 1}),
    httpx.Response(200, json={'subject_id': str(uuid4()), 'revision': 1,
        'email': 'buyer@example.invalid', 'email_sample': True})])
async def test_unverified_or_denied_recipient_never_calls_orders(result, monkeypatch):
    store = Store()
    await notices.persist(store, event())
    monkeypatch.setattr(notices, 'headers', lambda *args: {})
    identity = Client(lambda *args: result)
    orders = Client(lambda *args: pytest.fail('No receipt before verified delivery'))
    app = SimpleNamespace(state=SimpleNamespace(identity=identity, orders=orders, pool=store))
    assert not await notices.deliver(app, store.row, uuid4(), '')
    assert orders.calls == []


def test_event_authentication_is_closed(monkeypatch):
    settings = SimpleNamespace(service_auth_public_key='synthetic', auth_issuer='beirut-time-identity')
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)), headers={})
    with pytest.raises(HTTPException) as exc:
        notices.authorize(event(), request)
    assert exc.value.status_code == 401
    request.headers = {'Authorization': 'Bearer synthetic'}
    monkeypatch.setattr(notices.jwt, 'decode', lambda *args, **kwargs: {'type': 'user', 'sub': 'orders'})
    with pytest.raises(HTTPException) as exc:
        notices.authorize(event(), request)
    assert exc.value.status_code == 403
    monkeypatch.setattr(notices.jwt, 'decode', lambda *args, **kwargs: {'type': 'service', 'sub': 'orders'})
    notices.authorize(event(), request)
    with pytest.raises(HTTPException) as exc:
        notices.authorize(event().model_copy(update={'source': 'catalog'}), request)
    assert exc.value.status_code == 403


def test_equivalent_event_key_order_preserves_retry_identity():
    original = event()
    reordered = original.model_copy(update={
        'data': dict(reversed(list(original.data.items()))), 'request_id': 'retry-002'})
    assert notices.fingerprint(original) == notices.fingerprint(reordered)


@pytest.fixture(autouse=True)
def assigned_recovery_operator(monkeypatch):
    monkeypatch.setenv('BT_PAYMENT_NOTICE_OPERATOR_ID', '00000000-0000-0000-0000-000000000004')


class RecoveryStore(Store):
    def __init__(self):
        super().__init__()
        self.now = NOW
        self.recovery = None

    async def execute(self, sql, *args):
        await super().execute(sql, *args)
        if 'INSERT INTO l22_payment_notice_recovery' in sql and self.recovery is None:
            self.recovery = {
                'operator_id': args[1], 'response_due_at': NOW + timedelta(hours=24),
                'escalation_due_at': NOW + timedelta(hours=48),
                'escalated_at': None, 'resolved_at': None,
            }
        if 'INSERT INTO l22_payment_notice_recovery' in sql and self.recovery['operator_id'] is None:
            self.recovery['operator_id'] = args[1]
        if 'escalated_at=COALESCE' in sql and self.recovery:
            assert 'n.acknowledged_at IS NULL' in sql
            assert 'r.escalation_due_at<=now()' in sql
            if not self.row.get('acknowledged_at') and self.now >= self.recovery['escalation_due_at']:
                self.recovery['escalated_at'] = self.recovery['escalated_at'] or self.now
        if 'SET resolved_at=now()' in sql and self.recovery and self.row.get('acknowledged_at'):
            self.recovery['resolved_at'] = self.now

    async def fetchval(self, sql, *args):
        if 'acknowledged_at=CASE' in sql:
            if args[2]:
                self.row['acknowledged_at'] = self.now
            self.row['available_at'] = self.now + timedelta(seconds=args[3])
            self.row['lease_token'] = None
            return args[0]
        return await super().fetchval(sql, *args)

    async def fetch(self, sql, lease):
        if self.row.get('acknowledged_at') or self.row.get('available_at', NOW) > self.now:
            return []
        self.row['attempts'] = self.row.get('attempts', 0) + 1
        self.row['lease_token'] = lease
        return [dict(self.row)] if not self.row.get('acknowledged_at') else []


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['contact', 'denied', 'timeout'])
async def test_failed_delivery_has_fixed_recovery_deadlines_and_escalates(failure, monkeypatch):
    store = RecoveryStore()
    await notices.persist(store, event())
    monkeypatch.setattr(notices, 'unit_of_work', lambda pool: store.transaction())
    monkeypatch.setattr(notices, 'headers', lambda *args: {})
    identity = Client(lambda *args: httpx.Response(200, json={
        'subject_id': str(BUYER), 'revision': 4,
        'email': 'buyer@example.invalid', 'email_sample': True}))
    if failure == 'contact':
        identity.callback = lambda *args: httpx.Response(403)
    orders = Client(lambda *args: Unavailable('orders', 'timeout') if failure == 'timeout'
        else httpx.Response(403))
    app = SimpleNamespace(state=SimpleNamespace(identity=identity, orders=orders, pool=store))
    original_receipt = notices.receipt(store.row)
    assert store.recovery is None
    await notices.tick(app, '')
    original_recovery = deepcopy(store.recovery)
    store.now = NOW + timedelta(hours=24)
    await notices.tick(app, '')
    assert store.recovery == original_recovery
    store.now = NOW + timedelta(hours=48)
    await notices.tick(app, '')
    assert store.recovery['escalated_at'] == store.now
    assert store.recovery['resolved_at'] is None
    assert store.recovery['operator_id'] == UUID('00000000-0000-0000-0000-000000000004')
    assert store.recovery['response_due_at'] == NOW + timedelta(hours=24)
    assert store.recovery['escalation_due_at'] == NOW + timedelta(hours=48)
    store.now += timedelta(hours=1)
    # A replacement configuration cannot silently reassign an existing recovery.
    monkeypatch.setenv('BT_PAYMENT_NOTICE_OPERATOR_ID', '00000000-0000-0000-0000-000000000005')
    await notices.tick(app, '')
    assert store.recovery['operator_id'] == original_recovery['operator_id']
    assert store.recovery['escalated_at'] == NOW + timedelta(hours=48)
    identity.callback = lambda *args: httpx.Response(200, json={
        'subject_id': str(BUYER), 'revision': 4,
        'email': 'buyer@example.invalid', 'email_sample': True})
    orders.callback = lambda *args: httpx.Response(200)
    store.now += timedelta(minutes=1)
    await notices.tick(app, '')
    assert store.recovery['resolved_at'] == store.now
    assert notices.receipt(store.row) == original_receipt
    assert all(call[2]['json'] == original_receipt for call in orders.calls)


@pytest.mark.asyncio
async def test_missing_signing_key_still_records_escalation(monkeypatch):
    monkeypatch.delenv('BT_PAYMENT_NOTICE_OPERATOR_ID', raising=False)
    store = RecoveryStore()
    assert await notices.persist(store, event())
    assert store.recovery is None
    monkeypatch.setattr(notices, 'unit_of_work', lambda pool: store.transaction())
    app = SimpleNamespace(state=SimpleNamespace(pool=store))
    await notices.tick(app, None)
    assert store.recovery['operator_id'] is None
    assert store.recovery['response_due_at'] == NOW + timedelta(hours=24)
    assert store.recovery['escalation_due_at'] == NOW + timedelta(hours=48)
    assert store.row.get('acknowledged_at') is None
    assert store.row['available_at'] == NOW + timedelta(seconds=2)
    store.now = NOW + timedelta(hours=48)
    await notices.tick(app, None)
    assert store.recovery['escalated_at'] == store.now
    assert store.recovery['resolved_at'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 503])
async def test_delivery_without_recovery_operator(status, monkeypatch):
    monkeypatch.delenv('BT_PAYMENT_NOTICE_OPERATOR_ID')
    store = RecoveryStore()
    assert await notices.persist(store, event())
    assert store.recovery is None
    monkeypatch.setattr(notices, 'unit_of_work', lambda pool: store.transaction())
    monkeypatch.setattr(notices, 'headers', lambda *args: {})
    identity = Client(lambda *args: httpx.Response(200, json={
        'subject_id': str(BUYER), 'revision': 4,
        'email': 'buyer@example.invalid', 'email_sample': True}))
    orders = Client(lambda *args: httpx.Response(status))
    app = SimpleNamespace(state=SimpleNamespace(identity=identity, orders=orders, pool=store))
    await notices.tick(app, '')
    assert len(orders.calls) == 1
    if status == 200:
        assert store.row['acknowledged_at'] == NOW
        assert store.recovery is None
    else:
        assert store.row.get('acknowledged_at') is None
        assert store.row['available_at'] == NOW + timedelta(seconds=2)
        assert store.recovery['operator_id'] is None
        assert store.recovery['resolved_at'] is None
        monkeypatch.setenv('BT_PAYMENT_NOTICE_OPERATOR_ID', str(UUID(int=4)))
        store.now += timedelta(seconds=2)
        await notices.tick(app, '')
        assert store.recovery['operator_id'] == UUID(int=4)
        assert store.recovery['response_due_at'] == NOW + timedelta(hours=24)
