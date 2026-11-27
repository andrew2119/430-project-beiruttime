"""Import only this lane's modules; no runtime boot, database or services."""

import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def lane_modules(monkeypatch):
    def namespace(name, relative):
        module = ModuleType(name)
        module.__path__ = [str(ROOT / relative)]
        monkeypatch.setitem(sys.modules, name, module)

    namespace("bt_contracts", "packages")
    namespace("bt_contracts.orders", "packages/contracts-orders")
    namespace("bt_contracts.auction", "packages/contracts-auction")
    namespace("bt_contracts.pricing", "packages/contracts-pricing")
    namespace("service_app", "services/orders/runtime/service_app")
    namespace("l13_payment_module", "services/orders/modules/payments")

    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    # Mark imported children for restoration too: each test has fresh modules.
    before = set(sys.modules)
    yield load
    for name in set(sys.modules) - before:
        if name.startswith(("service_app.", "bt_contracts.", "l13_payment_module.")):
            sys.modules.pop(name, None)


@pytest.fixture
def close_consumer(lane_modules, monkeypatch):
    now = datetime.now(timezone.utc)
    lot = {key: uuid4() for key in ("id", "watch_id", "listing_id", "seller_id", "leader_id")}
    lot.update(seller_organization_id=None, currency="USD", revision=3, end_version=1, close_version=0,
               mode="bidding", accepted_sequence=1, current_minor=500000, reserve_minor=None,
               scheduled_ends_at=now, ends_at=now + timedelta(hours=2))
    state = {"row": None, "transitions": [], "locks": [], "events": []}

    async def lock_lot(tx, auction_id):
        assert auction_id == lot["id"]
        state["locks"].append("canonical_auction")
        return lot

    async def server_now(tx):
        return now

    async def transition(tx, auction_id, **binding):
        assert state["locks"][-1] == "canonical_auction"
        assert binding["expected_revision"] == lot["revision"]
        assert binding["expected_end_version"] == lot["end_version"]
        assert binding["from_mode"] == lot["mode"] == "bidding"
        assert now >= lot["scheduled_ends_at"]
        state["transitions"].append(binding)
        lot.update(mode=binding["to_mode"], revision=lot["revision"] + 1, close_version=lot["close_version"] + 1)
        return lot

    kernel = ModuleType("service_app.kernel")
    kernel.lock_lot, kernel.server_now, kernel.transition = lock_lot, server_now, transition
    monkeypatch.setitem(sys.modules, "service_app.kernel", kernel)
    module = lane_modules("lane_closing_service", "services/auction/modules/closing/service.py")

    async def fetchrow(sql, *args):
        assert state["locks"][-1] == "canonical_auction"
        if sql.startswith("SELECT * FROM l13_auction_closes"):
            return state["row"]
        if sql.lstrip().startswith("UPDATE l13_auction_closes"):
            from datetime import timedelta
            state["row"].update(responsible_operator_id=args[1], next_action=args[2],
                                response_due_at=state["row"].get("response_due_at") or now + timedelta(hours=24),
                                escalation_due_at=state["row"].get("escalation_due_at") or now + timedelta(hours=48),
                                escalated_at=state["row"].get("escalated_at"))
            return state["row"]
        assert sql.lstrip().startswith("INSERT INTO l13_auction_closes")
        if "'ended_legacy_review'" in sql:
            row = {"auction_id": args[0], "id": args[1], "end_version": args[2], "close_version": args[3],
                   "winner_id": None, "closing_minor": args[4], "state": "ended_legacy_review", "reason": args[5],
                   "quote_request": None, "scheduled_ends_at": args[6], "order_id": None}
        else:
            row = {"auction_id": args[0], "id": args[1], "end_version": args[2], "close_version": args[3],
                   "winner_id": args[4], "closing_minor": args[5], "state": args[6], "reason": args[7],
                   "quote_request": args[8], "scheduled_ends_at": args[9], "order_id": None}
        state["row"] = row
        return row

    async def fetch(sql):
        assert "LIMIT 10 FOR UPDATE SKIP LOCKED" in sql
        assert "responsible_operator_id IS NULL" in sql
        row = state["row"]
        return [row] if row and row.get("responsible_operator_id") is None else []

    tx = SimpleNamespace(fetchrow=fetchrow, fetch=fetch)

    @asynccontextmanager
    async def unit_of_work(_):
        saved_state, saved_lot = copy.deepcopy(state), copy.deepcopy(lot)
        try:
            yield tx
        except BaseException:
            state.clear()
            state.update(saved_state)
            lot.clear()
            lot.update(saved_lot)
            raise

    async def enqueue(tx, event, destinations):
        state["events"].append(event)

    monkeypatch.setattr(module, "unit_of_work", unit_of_work)
    monkeypatch.setattr(module, "enqueue", enqueue)
    app = SimpleNamespace(state=SimpleNamespace(pool=object(), closing_operator_id=uuid4()))
    return module, app, lot, state, now
