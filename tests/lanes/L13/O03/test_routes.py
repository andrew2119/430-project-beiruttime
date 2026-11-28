"""HTTP adapters preserve authenticated producer context and transaction ownership."""

from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
import sys

import pytest
from bt_contracts_core.errors import AccessDenied


@pytest.mark.asyncio
async def test_internal_routes_pass_authenticated_producer(modules, monkeypatch):
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    namespace = ModuleType('o03_journal')
    namespace.__path__ = [str(root / 'services/orders/modules/journal')]
    monkeypatch.setitem(sys.modules, 'o03_journal', namespace)
    route = modules('o03_journal.routes', 'services/orders/modules/journal/routes.py')
    tx, reader, body = object(), object(), object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=object(), money_policy_reader=reader)),
                              state=SimpleNamespace(request_id='route-check'))

    @asynccontextmanager
    async def transaction(pool):
        yield tx

    async def reserve(connection, command, policy, reference, *, producer):
        assert (connection, command, policy, reference, producer) == (tx, body, reader, 'route-check', 'trust')
        return {'state': 'pending'}

    async def lookup(connection, command, policy, *, producer):
        assert (connection, command, policy, producer) == (tx, body, reader, 'trust')
        return {'state': 'confirmed'}

    monkeypatch.setattr(route, 'service', lambda request, allowed: 'trust')
    monkeypatch.setattr(route, 'unit_of_work', transaction)
    monkeypatch.setattr(route, 'reserve', reserve)
    monkeypatch.setattr(route, 'lookup', lookup)
    assert await route.reserve_movement(body, request) == {'state': 'pending'}
    assert await route.lookup_movement(body, request) == {'state': 'confirmed'}

    def denied(request, allowed):
        raise AccessDenied('Current producer scope required')

    monkeypatch.setattr(route, 'service', denied)
    with pytest.raises(AccessDenied):
        await route.reserve_movement(body, request)
    with pytest.raises(AccessDenied):
        await route.lookup_movement(body, request)


@pytest.mark.asyncio
async def test_checkout_reads_current_money_inside_owned_transaction(modules, monkeypatch):
    from pathlib import Path
    from uuid import uuid4
    from datetime import datetime, timezone
    root = Path(__file__).resolve().parents[4]
    namespace = ModuleType('o03_payments')
    namespace.__path__ = [str(root / 'services/orders/modules/payments')]
    monkeypatch.setitem(sys.modules, 'o03_payments', namespace)
    route = modules('o03_payments.routes', 'services/orders/modules/payments/routes.py')
    order_id = uuid4()
    order = {'id': order_id, 'currency': 'USD', 'state': 'paid_held', 'deadline': None}
    readiness = {'state': 'unpaid', 'movement_status': 'refunded', 'held_minor': 0}
    active = False

    @asynccontextmanager
    async def transaction(pool):
        nonlocal active
        active = True
        yield tx
        active = False

    async def lock(connection, subject):
        assert active and connection is tx and subject == order_id
        return order

    async def current(connection, subject):
        await lock(connection, subject)
        return readiness

    async def fetchrow(sql, *args):
        return {'snapshot': {}}

    async def fetch(sql, *args):
        return []

    async def fetchval(sql, *args):
        return datetime(2026, 11, 16, tzinfo=timezone.utc) if 'clock_timestamp' in sql else 'acknowledged'

    tx = SimpleNamespace(fetchrow=fetchrow, fetch=fetch, fetchval=fetchval)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=object())))
    monkeypatch.setattr(route, 'unit_of_work', transaction)
    monkeypatch.setattr(route, 'lock_order', lock)
    monkeypatch.setattr(route, 'financial_readiness', current)
    monkeypatch.setattr(route, 'owner', lambda actor, record: None)
    monkeypatch.setattr(route, 'order_fact', lambda record: record)
    value = await route.checkout(order_id, request, object())
    assert value['financial_readiness'] == readiness
    assert value['order']['state'] == 'paid_held'
    assert value['payable'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['select_method', 'start'])
async def test_checkout_reconciliation_denies_new_money_action(modules, monkeypatch, action):
    from pathlib import Path
    from uuid import uuid4
    root = Path(__file__).resolve().parents[4]
    namespace = ModuleType('o03_fenced_payments')
    namespace.__path__ = [str(root / 'services/orders/modules/payments')]
    monkeypatch.setitem(sys.modules, 'o03_fenced_payments', namespace)
    route = modules('o03_fenced_payments.routes', 'services/orders/modules/payments/routes.py')
    order_id = uuid4()
    order = {'id': order_id}
    async def fetchrow(sql, *args):
        return order
    async def fetchval(sql, *args):
        assert 'l13_money_reconciliations' in sql
        return True
    async def lock(tx, subject):
        return order
    async def command(pool, actor, key, kind, body, apply, **kwargs):
        return await apply(tx)
    @asynccontextmanager
    async def transaction(pool):
        yield tx
    async def current(tx, subject, value):
        return value
    tx = SimpleNamespace(fetchrow=fetchrow, fetchval=fetchval)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=tx)),state=SimpleNamespace(request_id='held-check'))
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=uuid4()))
    monkeypatch.setattr(route, 'owner', lambda *args: None)
    monkeypatch.setattr(route, 'lock_order', lock)
    monkeypatch.setattr(route, 'command', command)
    monkeypatch.setattr(route, 'secret', lambda: None)
    monkeypatch.setattr(route, 'unit_of_work', transaction)
    monkeypatch.setattr(route, 'current_payment_result', current)
    body = SimpleNamespace(model_dump=lambda **kwargs: {})
    value = await getattr(route, action)(order_id, body, request, actor, 'original-reference')
    assert value == {'status': 'pending', 'code': 'reconciliation_required'}


@pytest.mark.asyncio
async def test_initiation_requires_recovery_assignment_before_attempt_or_extension(modules, monkeypatch):
    from pathlib import Path
    from uuid import uuid4
    from datetime import datetime, timezone
    from bt_contracts_core.errors import PublicError
    root = Path(__file__).resolve().parents[4]
    namespace = ModuleType('o03_assigned_payments')
    namespace.__path__ = [str(root / 'services/orders/modules/payments')]
    monkeypatch.setitem(sys.modules, 'o03_assigned_payments', namespace)
    route = modules('o03_assigned_payments.routes', 'services/orders/modules/payments/routes.py')
    order_id, buyer_id = uuid4(), uuid4()
    order = dict(id=order_id, buyer_id=buyer_id, revision=3, state='awaiting_payment',
                 currency='USD', total_minor=515000)
    writes = []

    async def fetchrow(sql, *args):
        if 'FROM l08_orders' in sql:
            return order
        if 'FROM l13_payment_attempts' in sql:
            return None
        if 'FROM l13_order_quotes' in sql:
            return {'quote_revision': 2, 'snapshot': {'reviewed_at': '2026-11-16T00:00:00Z'}}
        writes.append(sql)
        raise AssertionError(sql)

    async def fetchval(sql, *args):
        if 'clock_timestamp' in sql:
            return datetime(2026, 11, 16, tzinfo=timezone.utc)
        if 'l13_quote_commitments' in sql:
            return 'acknowledged'
        if 'l13_money_reconciliations' in sql or 'l13_payment_recovery_assignments' in sql:
            return None
        raise AssertionError(sql)

    async def lock(tx, subject):
        return order

    async def command(pool, actor, key, kind, body, apply, **kwargs):
        return await apply(tx)

    tx = SimpleNamespace(fetchrow=fetchrow, fetchval=fetchval)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=tx)),
                              state=SimpleNamespace(request_id='assignment-check'))
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=buyer_id))
    body = SimpleNamespace(expected_revision=3, quote_revision=2, total_minor=515000,
                           currency='USD', route='card', model_dump=lambda **kwargs: {})
    monkeypatch.setattr(route, 'owner', lambda *args: None)
    monkeypatch.setattr(route, 'lock_order', lock)
    monkeypatch.setattr(route, 'command', command)
    monkeypatch.setattr(route, 'secret', lambda: None)
    monkeypatch.setattr(route, 'can_initiate', lambda *args: True)
    monkeypatch.setattr(route, 'initiated_until', lambda *args: None)
    with pytest.raises(PublicError, match='recovery_assignment_unavailable'):
        await route.start(order_id, body, request, actor, 'retained-reference')
    assert not writes and order['state'] == 'awaiting_payment' and order['revision'] == 3
