from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_recovered_notice_is_same_durable_intent_and_never_delivery(lane_modules, monkeypatch):
    module = lane_modules("service_app.payment_notices", "services/orders/runtime/service_app/payment_notices.py")
    event_id = uuid4()
    tx = SimpleNamespace(fetchval=AsyncMock(side_effect=[event_id, None]))
    enqueue = AsyncMock()
    monkeypatch.setattr(module, "enqueue", enqueue)
    order = {"id": uuid4(), "buyer_id": uuid4(), "revision": 1, "is_demo": True,
             "notified_at": None, "deadline": None, "state": "awaiting_notification"}
    await module.ensure_payment_notice(tx, order, "recovery")
    await module.ensure_payment_notice(tx, order, "retry")
    enqueue.assert_awaited_once()
    envelope = enqueue.await_args.args[1]
    assert envelope.id == event_id
    assert envelope.type == "orders.payment-action-required.v3"
    assert envelope.data["buyer_id"] == str(order["buyer_id"])
    assert envelope.data["order_id"] == str(order["id"])
    assert envelope.data["required"] is True
    assert enqueue.await_args.args[2] == ["communications"]
    assert order["notified_at"] is order["deadline"] is None
    assert order["state"] == "awaiting_notification"
    assert "ON CONFLICT(order_id) DO NOTHING" in tx.fetchval.await_args.args[0]
