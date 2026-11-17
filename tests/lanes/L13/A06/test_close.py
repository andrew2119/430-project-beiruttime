from datetime import timedelta
import json

import pytest
from bt_contracts_core.errors import PublicError


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-1, 0, 1])
async def test_end_boundary(close_consumer, offset):
    module, app, lot, state, now = close_consumer
    lot["scheduled_ends_at"] = now - timedelta(microseconds=offset)
    if offset < 0:
        with pytest.raises(PublicError, match="auction_not_ended"):
            await module.close(app, lot["id"], 1, "end")
        assert state["row"] is None
    else:
        result = await module.close(app, lot["id"], 1, "end")
        assert result["status"] == "allocation_pending"
        assert len(state["transitions"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_bids", "reserve_not_met", "reserve_equal"])
async def test_public_price_decides_reserve(close_consumer, case):
    module, app, lot, state, _ = close_consumer
    if case == "no_bids":
        lot.update(accepted_sequence=0, leader_id=None)
    else:
        lot["reserve_minor"] = lot["current_minor"] + (1 if case == "reserve_not_met" else 0)
    result = await module.close(app, lot["id"], 1, "reserve")
    assert result["status"] == ("allocation_pending" if case == "reserve_equal" else "no_sale")
    if case != "reserve_equal":
        assert result["winner"] is None
        assert json.loads(state["row"]["quote_request"]) is None


@pytest.mark.asyncio
async def test_restart_replays_original_decision(close_consumer):
    module, app, lot, state, _ = close_consumer
    first = await module.close(app, lot["id"], 1, "original")
    assert await module.close(app, lot["id"], 999, "lost-reply") == first
    assert len(state["events"]) == len(state["transitions"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["prebid_pending", "prebid_reserved"])
async def test_legacy_hold_is_not_released(close_consumer, mode):
    module, app, lot, state, _ = close_consumer
    lot["mode"] = mode
    result = await module.close(app, lot["id"], 1, "legacy")
    assert result["status"] == "ended_legacy_review"
    assert result["winner"] is None
    assert lot["mode"] == mode
    assert not state["transitions"]


@pytest.mark.asyncio
async def test_recovery_schema(close_consumer):
    module, app, lot, state, now = close_consumer
    await module.close(app, lot["id"], 1, "close")
    state["row"].update(result_revision=1, next_attempt_at=now)
    from bt_contracts.auction.closing.v3 import CloseResultV3

    first = CloseResultV3.model_validate(module.recovery(state["row"], "USD"))
    assert first.pending_reason == "allocation_reconciliation"
    assert first.allocation_operation == "close:" + str(lot["id"])
    state["row"].update(state="allocation_denied", result_revision=2)
    denied = CloseResultV3.model_validate(module.recovery(state["row"], "USD"))
    assert denied.operation_id == first.operation_id
    assert denied.allocation_operation == first.allocation_operation
    assert denied.next_actor == "operator"
    assert denied.revision == 2


def test_published_recovery_fixtures(lane_modules):
    from pathlib import Path
    from bt_contracts.auction.closing.v3 import CloseResultV3

    fixture = Path(__file__).resolve().parents[4] / "packages/contracts-auction/closing/fixtures/recovery.v3.json"
    for case in json.loads(fixture.read_text())["cases"]:
        if "result" in case:
            CloseResultV3.model_validate(case["result"])
        else:
            assert case["error"]["code"] == "stale_end_version"
            assert case["error"]["status"] == 409
