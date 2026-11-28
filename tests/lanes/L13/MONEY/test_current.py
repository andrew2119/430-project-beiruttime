from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("source,status,current", [(1, "reserved", True), (9, "reserved", False), (1, "available", False)])
async def test_current_commitment_checks_actual_source_not_historic_success(lane_modules, monkeypatch, source, status, current):
    import bt_runtime.app.db as database

    module = lane_modules("current_commitment_routes", "services/orders/modules/allocation/commitment/routes.py")
    order = dict(id=UUID(int=1), watch_id=UUID(int=2), buyer_id=UUID(int=3), organization_id=None,
                 quote_id=UUID(int=4), revision=2, state="awaiting_notification", notified_at=None, deadline=None)
    tx = SimpleNamespace(fetchval=AsyncMock(return_value=3))
    @asynccontextmanager
    async def transaction(pool):
        yield tx
    monkeypatch.setattr(database, "unit_of_work", transaction)
    import service_app.orders_kernel as kernel
    monkeypatch.setattr(kernel, "lock_order", AsyncMock(return_value=order))
    monkeypatch.setattr(module, "lock_watch", AsyncMock(return_value=dict(source_id=UUID(int=source),status=status,revision=5)))
    permission = AsyncMock()
    def service(request, callers):
        assert "auction" in callers
        permission.called_once = True
    monkeypatch.setattr(module, "service", service)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=object())))
    proof = await module.current_commitment(order["id"], request)
    assert permission.called_once
    assert proof.current is current
    assert proof.payment_authority is False
    assert proof.notified_at is proof.deadline is None
    assert proof.quote_revision == 3 and proof.watch_revision == 5
