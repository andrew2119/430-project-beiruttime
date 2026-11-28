from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from bt_contracts_core.models import EventEnvelope
from bt_runtime.app.settings import Settings
from service_app import database, payment_notices


@pytest.mark.asyncio
@pytest.mark.parametrize("database_access", ["core-only"], indirect=True)
async def test_failed_notice_can_be_held_and_assigned_later(database_access, monkeypatch):
    monkeypatch.delenv("BT_PAYMENT_NOTICE_OPERATOR_ID", raising=False)
    await database.migrate(database_access.owner_url, Settings().modules_path)
    pool = await database.create_pool(database_access.runtime_url)
    order, buyer, operator, replacement = (uuid4() for _ in range(4))
    event = EventEnvelope(
        type="orders.payment-action-required.v3", source="orders", subject=str(order),
        request_id="payment-test", time=datetime.now(timezone.utc),
        data={"order_id": str(order), "buyer_id": str(buyer), "recipient_id": str(buyer),
              "revision": 2, "required": True, "sample": False, "simulated": True},
    )
    try:
        async with database.unit_of_work(pool) as tx:
            assert await payment_notices.persist(tx, event)
            row = await tx.fetchrow("SELECT * FROM l22_payment_notices WHERE event_id=$1", event.id)
            assert row["order_revision"] == 2
            assert await tx.fetchval("SELECT count(*) FROM l22_payment_notice_recovery") == 0
        await payment_notices.tick(SimpleNamespace(state=SimpleNamespace(pool=pool)), None)
        async with database.unit_of_work(pool) as tx:
            held = await tx.fetchrow("SELECT * FROM l22_payment_notice_recovery WHERE event_id=$1", event.id)
            assert held["operator_id"] is None
            assert held["resolved_at"] is None
            assert held["response_due_at"] == row["notified_at"] + timedelta(hours=24)
            assert held["escalation_due_at"] == row["notified_at"] + timedelta(hours=48)
            for configured in (operator, replacement):
                monkeypatch.setenv("BT_PAYMENT_NOTICE_OPERATOR_ID", str(configured))
                await payment_notices.hold_for_recovery(tx, row)
            assigned = await tx.fetchrow("SELECT * FROM l22_payment_notice_recovery WHERE event_id=$1", event.id)
            assert dict(assigned) == dict(held) | {"operator_id": operator}
    finally:
        await pool.close()
