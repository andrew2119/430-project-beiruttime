from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from bt_contracts_core.errors import AccessDenied, PublicError


@pytest.fixture
def checkout_route(lane_modules):
    route = lane_modules("l13_payment_module.routes", "services/orders/modules/payments/routes.py")
    now = datetime.now(timezone.utc)
    row = {key: uuid4() for key in ("id", "watch_id", "listing_id", "buyer_id", "seller_id", "quote_id")}
    row.update(organization_id=None, state="awaiting_notification", currency="USD", total_minor=515000,
               revision=1, deadline=None, is_demo=True, notified_at=None, payment_method=None,
               initiation_extended_until=None, order_kind="sale")
    quote = {"snapshot": {"revision": 2, "reviewed_at": now.isoformat()}}
    attempts = []

    async def fetchrow(sql, *args):
        if sql.startswith("UPDATE l08_orders SET payment_method"):
            row.update(payment_method=args[1], deadline=args[2], revision=row["revision"] + 1)
            return row
        if "l08_orders" in sql:
            return row
        if "l13_order_quotes" in sql:
            return quote
        raise AssertionError(sql)

    tx = SimpleNamespace(fetchrow=fetchrow, fetch=AsyncMock(return_value=attempts), fetchval=AsyncMock(return_value=now))

    @asynccontextmanager
    async def acquire():
        yield tx

    pool = SimpleNamespace(acquire=acquire, isolated_tx=tx)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)), state=SimpleNamespace(request_id="checkout-unit"))
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=row["buyer_id"], organization_id=None), roles=["buyer"])
    return route, request, actor, row, attempts, now


@pytest.mark.asyncio
async def test_unnotified_checkout_has_no_hidden_deadline_or_authority(checkout_route):
    route, request, actor, row, _, _ = checkout_route
    result = await route.checkout(row["id"], request, actor)
    assert result["method_deadlines"] == {"card": None, "whish": None, "omt": None}
    assert result["order"]["deadline"] is result["order"]["notified_at"] is None
    assert not result["payable"]


@pytest.mark.asyncio
async def test_server_projects_routes_from_one_original_notice(checkout_route):
    route, request, actor, row, _, now = checkout_route
    row.update(state="awaiting_payment", notified_at=now - timedelta(hours=1), deadline=now + timedelta(hours=47))
    result = await route.checkout(row["id"], request, actor)
    assert result["method_deadlines"] == {"card": now + timedelta(hours=23), "whish": now + timedelta(hours=47), "omt": now + timedelta(hours=47)}
    assert result["payable"]
    row["initiation_extended_until"] = now + timedelta(hours=71)
    extended = await route.checkout(row["id"], request, actor)
    assert set(extended["method_deadlines"].values()) == {now + timedelta(hours=71)}


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt_state", ["pending", "held", "confirmed"])
async def test_uncertain_attempt_is_not_another_payable_checkout(checkout_route, attempt_state):
    route, request, actor, row, attempts, now = checkout_route
    row.update(state="payment_unknown", notified_at=now, deadline=now + timedelta(hours=48))
    attempts.append({"id": uuid4(), "order_id": row["id"], "buyer_id": row["buyer_id"], "quote_id": row["quote_id"],
                     "quote_revision": 2, "route": "omt", "reference": "SIM-test", "currency": "USD",
                     "total_minor": 515000, "state": attempt_state, "sequence": 1})
    assert not (await route.checkout(row["id"], request, actor))["payable"]


@pytest.mark.asyncio
async def test_method_switch_uses_original_notice_without_restarting_time(checkout_route, monkeypatch):
    route, request, actor, row, _, now = checkout_route
    tx = request.app.state.pool.isolated_tx
    tx.fetchval = AsyncMock(side_effect=lambda sql, *args: now if sql == "SELECT clock_timestamp()" else None)
    row.update(state="awaiting_payment", notified_at=now - timedelta(hours=2), deadline=now + timedelta(hours=46))

    async def command(pool, actor_key, key, action, payload, handler, **kwargs):
        return await handler(tx)

    monkeypatch.setattr(route, "command", command)
    for method, remaining in (("card", 22), ("whish", 46), ("omt", 46)):
        result = await route.select_method(row["id"], route.SelectPaymentMethod(expected_revision=row["revision"], route=method),
                                           request, actor, "method-" + method)
        assert result["status"] == "succeeded"
        assert row["deadline"] == now + timedelta(hours=remaining)
        assert row["notified_at"] == now - timedelta(hours=2)
    row["deadline"] = now
    denied = await route.select_method(row["id"], route.SelectPaymentMethod(expected_revision=row["revision"], route="whish"),
                                       request, actor, "elapsed")
    assert denied["code"] == "deadline_elapsed"


@pytest.mark.asyncio
async def test_archive_or_other_buyer_never_exposes_active_amount(checkout_route):
    route, request, actor, row, _, _ = checkout_route
    row["currency"] = "LBP"
    with pytest.raises(PublicError, match="legacy_currency_reconciliation_required"):
        await route.checkout(row["id"], request, actor)
    actor.actor.subject_id = uuid4()
    with pytest.raises(AccessDenied):
        await route.checkout(row["id"], request, actor)
