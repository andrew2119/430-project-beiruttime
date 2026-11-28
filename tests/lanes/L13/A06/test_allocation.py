from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from bt_contracts_core.errors import PublicError


@pytest.fixture
def allocation(lane_modules, monkeypatch):
    module = lane_modules("closing_reconciliation", "services/auction/modules/closing/reconcile.py")
    auction, buyer, watch, listing, quote, order = [uuid4() for _ in range(6)]
    payload = {
        "operation_key": "close:" + str(auction), "watch_id": str(watch),
        "listing_id": str(listing), "listing_revision": 1, "expected_revision": 3,
        "source_id": str(auction), "kind": "winner", "buyer_id": str(buyer),
        "quote_id": str(quote), "quote_revision": 1, "currency": "USD", "total_minor": 515000,
    }
    row = dict(auction_id=auction, winner_id=buyer, closing_minor=500000,
               allocation_payload=json.dumps(payload), state="allocation_pending",
               end_version=1, close_version=1, result_revision=1)
    state = dict(expired=False, calls=[], events=[], row=row)

    async def fetchrow(sql, *args):
        if row["state"] != "allocation_pending":
            return None
        row["lease"] = args[1]
        return row.copy()

    async def fetchval(sql, *args):
        assert "lease_until>clock_timestamp()" in sql
        if state["expired"] or args[1] != row["lease"]:
            return None
        assert "result_revision=result_revision+1" in sql
        row.update(state=args[2], order_id=args[3], reason=args[4], result_revision=2)
        return 1

    async def execute(sql, *args):
        assert "next_attempt_at" in sql

    tx = SimpleNamespace(fetchrow=fetchrow, fetchval=fetchval, execute=execute)

    @asynccontextmanager
    async def transaction(_=None):
        yield tx

    async def enqueue(tx, event, destinations):
        state["events"].append(event)

    monkeypatch.setattr(module, "unit_of_work", transaction)
    monkeypatch.setattr(module, "enqueue", enqueue)
    app = SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=transaction)))
    result = {"status": "succeeded", "order": {
        "id": str(order), **{k: payload[k] for k in
        ("buyer_id", "watch_id", "listing_id", "quote_id", "currency", "total_minor")},
    }}

    class Source:
        async def json(self, name, method, path, **kwargs):
            assert name == "orders" and method == "POST"
            assert path == "/internal/v2/allocations"
            assert kwargs["headers"]["Idempotency-Key"] == payload["operation_key"]
            state["calls"].append(kwargs["json"])
            if state.get("lost"):
                state["lost"] = False
                raise PublicError("source_unavailable", "Pending", status=503)
            return state.get("result", result)

    return module, app, auction, Source(), state, result


@pytest.mark.asyncio
async def test_lost_reply_restart_and_duplicate_use_one_allocation(allocation):
    module, app, auction, source, state, result = allocation
    state["lost"] = True
    await module.reconcile(app, source, auction)
    assert state["row"]["state"] == "allocation_pending"
    assert state["row"]["result_revision"] == 1
    await module.reconcile(app, source, auction)
    await module.reconcile(app, source, auction)
    assert state["calls"][0] == state["calls"][1]
    assert len(state["calls"]) == 2
    assert len(state["events"]) == 1
    assert str(state["row"]["order_id"]) == result["order"]["id"]


@pytest.mark.asyncio
async def test_expired_worker_cannot_finish_or_publish(allocation):
    module, app, auction, source, state, _ = allocation
    state["expired"] = True
    await module.reconcile(app, source, auction)
    assert state["row"]["state"] == "allocation_pending"
    assert not state["events"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("buyer_id", str(uuid4())), ("quote_id", str(uuid4())),
    ("id", 123), ("id", []), ("id", None),
    ("total_minor", True), ("total_minor", 515000.0), ("id", str(uuid4()).replace("-", "x")),
])
async def test_unverified_result_stays_pending(allocation, field, value):
    module, app, auction, source, state, result = allocation
    result["order"][field] = value
    await module.reconcile(app, source, auction)
    assert state["row"]["state"] == "allocation_pending"
    assert not state["events"]


@pytest.mark.asyncio
async def test_denial_keeps_winner_for_review(allocation):
    module, app, auction, source, state, _ = allocation
    winner = state["row"]["winner_id"]
    state["result"] = {"status": "denied", "code": "current_authority_denied"}
    await module.reconcile(app, source, auction)
    assert state["row"]["state"] == "allocation_denied"
    assert state["row"]["winner_id"] == winner
    assert state["row"]["order_id"] is None
    assert not state["events"]


@pytest.mark.parametrize("price,total,valid", [
    (500000, 515000, True), (50, 52, True), (49, 50, True),
    (500000, 515000.0, False), (500000, True, False),
    (500000, 500000, False), (-1, -1, False),
])
def test_exact_watch_economics(lane_modules, price, total, valid):
    module = lane_modules("closing_money", "services/auction/modules/closing/reconcile.py")
    assert module.valid_total(total, price) is valid


@pytest.mark.parametrize("value", [123, [], None, "00000000-0000-0000-0000-000000000000"])
def test_invalid_source_references(lane_modules, value):
    module = lane_modules("closing_reference", "services/auction/modules/closing/reconcile.py")
    with pytest.raises(ValueError):
        module.reference(value)
