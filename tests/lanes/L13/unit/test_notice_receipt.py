from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from bt_contracts_core.errors import AccessDenied, PublicError


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def notice_route(lane_modules, monkeypatch, signing_key):
    route = lane_modules("notice_receipt_route", "services/orders/modules/allocation/commitment/notices.py")
    now = datetime.now(timezone.utc)
    intent = {"event_id": uuid4(), "notice_id": None, "order_id": uuid4(), "buyer_id": uuid4(),
              "created_at": now - timedelta(minutes=5), "notified_at": None}
    order = {"id": intent["order_id"], "buyer_id": intent["buyer_id"], "state": "awaiting_notification",
             "currency": "USD", "revision": 1, "notified_at": None, "deadline": None}
    # Projection is not the subject of this router test.
    monkeypatch.setattr(route, "order_fact", lambda row: dict(row))
    monkeypatch.setattr(route, "audit", AsyncMock())
    monkeypatch.setattr(route, "record_fact", AsyncMock())
    calls = []

    async def fetchrow(sql, *args):
        calls.append(sql)
        if sql.startswith("SELECT * FROM l08_orders"):
            return order
        if sql.startswith("SELECT * FROM l13_payment_notices"):
            return intent
        if sql.startswith("UPDATE l08_orders"):
            order.update(notified_at=args[1], deadline=args[2], state="awaiting_payment", revision=order["revision"] + 1)
            return order
        raise AssertionError(sql)

    async def execute(sql, *args):
        calls.append(sql)
        assert sql.lstrip().startswith("UPDATE l13_payment_notices")
        intent.update(notice_id=args[1], notified_at=args[2])

    tx = SimpleNamespace(fetchrow=fetchrow, fetchval=AsyncMock(return_value=now), execute=execute)

    @asynccontextmanager
    async def unit_of_work(_):
        yield tx

    monkeypatch.setattr(route, "unit_of_work", unit_of_work)
    settings = SimpleNamespace(service_auth_public_key=signing_key.public_key(), auth_issuer="beirut-time-identity")
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, pool=object()))

    def request(producer="communications", audience="orders"):
        token = jwt.encode({"sub": producer, "type": "service", "iss": settings.auth_issuer,
                            "aud": audience, "iat": now, "exp": now + timedelta(minutes=1)},
                           signing_key, algorithm="RS256")
        return SimpleNamespace(app=app, headers={"Authorization": "Bearer " + token},
                               state=SimpleNamespace(request_id="receipt-check"))

    body = route.PaymentNoticeReceipt(**{key: intent[key] for key in ("event_id", "order_id", "buyer_id")},
                                     notice_id=uuid4(), notified_at=now, verified_delivery_recorded=True)
    return route, body, request, intent, order, calls


@pytest.mark.asyncio
async def test_original_durable_receipt_starts_clock_exactly_once(notice_route):
    route, body, request, intent, order, calls = notice_route
    first = await route.received(body, request())
    assert order["notified_at"] == body.notified_at
    assert order["deadline"] == body.notified_at + timedelta(hours=48)
    assert order["revision"] == 2
    again = await route.received(body, request())
    assert first == again
    route.audit.assert_awaited_once()
    route.record_fact.assert_awaited_once()
    assert "l08_orders" in calls[0] and "FOR UPDATE" in calls[0]
    assert "l13_payment_notices" in calls[1] and "FOR UPDATE" in calls[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("producer,audience", [("catalog", "orders"), ("orders", "orders"), ("communications", "catalog")])
async def test_only_communications_with_orders_audience_can_start_clock(notice_route, producer, audience):
    route, body, request, _, order, calls = notice_route
    with pytest.raises((AccessDenied, HTTPException)):
        await route.received(body, request(producer, audience))
    assert not calls
    assert order["notified_at"] is order["deadline"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["buyer_id", "order_id", "event_id"])
async def test_wrong_receipt_binding_cannot_start_clock(notice_route, field):
    route, body, request, _, order, _ = notice_route
    with pytest.raises(PublicError, match="notice_binding_mismatch"):
        await route.received(body.model_copy(update={field: uuid4()}), request())
    assert order["notified_at"] is order["deadline"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["notice_id", "notified_at"])
async def test_duplicate_notice_cannot_replace_original_time_or_notice(notice_route, field):
    route, body, request, _, order, _ = notice_route
    await route.received(body, request())
    replacement = uuid4() if field == "notice_id" else body.notified_at - timedelta(seconds=1)
    with pytest.raises(PublicError, match="notice_conflict"):
        await route.received(body.model_copy(update={field: replacement}), request())
    assert order["notified_at"] == body.notified_at
    assert order["revision"] == 2
