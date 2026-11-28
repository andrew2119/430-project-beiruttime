from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID
import sys

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("states,released", [([], True), (["declined"], True),
    (["declined", "declined"], True), (["pending"], False), (["held"], False), (["confirmed"], False)])
async def test_expiry_retains_receipt_only_with_atomic_release(lane_modules, monkeypatch, states, released):
    root = Path(__file__).resolve().parents[4]
    package = ModuleType("allocation_expiry")
    package.__path__ = [str(root / "services/orders/modules/allocation")]
    monkeypatch.setitem(sys.modules, "allocation_expiry", package)
    module = lane_modules("allocation_expiry.workers", "services/orders/modules/allocation/workers.py")
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    order = dict(id=UUID(int=1), watch_id=UUID(int=2), listing_id=UUID(int=3), revision=2,
                 currency="USD", state="payment_unknown", deadline=now)
    watch = dict(source_id=order["id"], status="reserved", revision=3)
    tx = SimpleNamespace(fetch=AsyncMock(side_effect=[[order], [{"state": state} for state in states]]),
                         fetchval=AsyncMock(return_value=now), execute=AsyncMock())
    active = []
    @asynccontextmanager
    async def transaction(pool):
        active.append(True)
        try:
            yield tx
        finally:
            active.pop()
    async def publish(*args):
        assert active  # Outbox, receipt and release use the same transaction.
    monkeypatch.setattr(module, "unit_of_work", transaction)
    monkeypatch.setattr(module, "lock_watch", AsyncMock(return_value=watch))
    monkeypatch.setattr(module, "audit", AsyncMock())
    event = AsyncMock(side_effect=publish)
    monkeypatch.setattr(module, "enqueue", event)
    assert await module.expire(None) == 1
    writes = [call.args for call in tx.execute.await_args_list]
    receipts = [args for args in writes if "INSERT INTO l13_unpaid_release_receipts" in args[0]]
    stock = [args for args in writes if "UPDATE l08_watches" in args[0]]
    assert bool(receipts) == bool(stock) == released
    if released:
        assert receipts[0][1:] == (order["id"], order["watch_id"], 3, now, len(states))
    assert event.await_args.args[1].data["outcome"] == ("release" if released else "hold")
    assert event.await_args.args[1].data["automatic_runner_up"] is False
