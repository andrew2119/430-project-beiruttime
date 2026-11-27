"""Consumer fixture for the published fixed-end lock seam, not engine/race proof."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from uuid import uuid4
import sys

import pytest
from bt_contracts_core.errors import PublicError


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

    tx = SimpleNamespace(fetchrow=fetchrow)

    @asynccontextmanager
    async def unit_of_work(_):
        yield tx

    async def enqueue(tx, event, destinations):
        state["events"].append(event)

    monkeypatch.setattr(module, "unit_of_work", unit_of_work)
    monkeypatch.setattr(module, "enqueue", enqueue)
    app = SimpleNamespace(state=SimpleNamespace(pool=object()))
    return module, app, lot, state, now


@pytest.mark.asyncio
async def test_scheduled_end_wins_over_old_extension_and_closes_once(close_consumer):
    module, app, lot, state, _ = close_consumer
    first = await module.close(app, lot["id"], 1, "fixed-end")
    assert first["status"] == "allocation_pending"
    assert state["row"]["winner_id"] == lot["leader_id"]
    assert len(state["transitions"]) == 1
    assert await module.close(app, lot["id"], 999, "replay") == first
    assert len(state["transitions"]) == len(state["events"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["prebid_pending", "prebid_reserved"])
async def test_legacy_money_ends_temporally_without_release_new_winner_or_resume(close_consumer, mode):
    module, app, lot, state, _ = close_consumer
    lot["mode"] = mode
    result = await module.close(app, lot["id"], 1, "legacy")
    from bt_contracts.auction.closing.v2 import CloseResultV2

    fact = CloseResultV2.model_validate(result)
    assert fact.status == "ended_legacy_review" and fact.close_version == 0
    assert result["winner"] is None and not result["order_available"]
    assert lot["mode"] == mode and lot["close_version"] == 0
    assert state["row"]["quote_request"] is None
    assert not state["transitions"]
    event = state["events"][0]
    assert event.type == "auction.ended-legacy-review.v2"
    assert event.data["financial_hold_retained"]
    assert not event.data["automatic_runner_up"] and not event.data["automatic_resume"]
    with pytest.raises(PublicError, match="contract_upgrade_required"):
        module.public(state["row"], "USD")


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["no_bids", "reserve_not_met"])
async def test_no_sale_has_no_winner_or_quote_intent(close_consumer, reason):
    module, app, lot, state, _ = close_consumer
    if reason == "no_bids":
        lot.update(accepted_sequence=0, leader_id=None)
    else:
        lot["reserve_minor"] = 600000
    result = await module.close(app, lot["id"], 1, "no-sale")
    assert result["reason"] == reason and result["status"] == "no_sale"
    assert state["row"]["winner_id"] is None
    assert state["row"]["quote_request"] == "null"


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["before", "missing_kernel", "stale_job"])
async def test_no_fallback_clock_or_stale_close_authority(close_consumer, boundary):
    module, app, lot, state, now = close_consumer
    version = 1
    if boundary == "before":
        lot["scheduled_ends_at"] = now + timedelta(microseconds=1)
    elif boundary == "missing_kernel":
        lot.pop("scheduled_ends_at")
    else:
        version = 2
    with pytest.raises(PublicError):
        await module.close(app, lot["id"], version, "denied")
    assert state["row"] is None and not state["events"] and not state["transitions"]


@pytest.mark.asyncio
async def test_legacy_currency_is_retained_not_converted_or_newly_allocated(close_consumer):
    module, app, lot, state, _ = close_consumer
    lot["currency"] = "LBP"
    result = await module.close(app, lot["id"], 1, "archive")
    assert result["status"] == "ended_legacy_review"
    assert result["closing_minor"] is result["currency"] is None
    assert state["row"]["closing_minor"] == 500000
    assert not state["transitions"]
