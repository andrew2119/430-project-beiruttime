from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,action", [
    ("allocation_denied", "review_allocation_denial"),
    ("closed", None),
])
async def test_repeated_close_reads_reconciled_result_under_lock(
    close_consumer, monkeypatch, outcome, action
):
    module, app, lot, state, _ = close_consumer
    app.state.closing_operator_id = None
    await module.close(app, lot["id"], 1, "original")
    state["row"]["result_revision"] = 1
    original = state["row"].copy()
    app.state.closing_operator_id = uuid4()
    reads = []
    writes = []

    async def fetchrow(sql, *args):
        if sql.startswith("SELECT"):
            reads.append(sql)
            # Reconciliation commits while the repeated close waits for the row.
            stale = state["row"].copy()
            state["row"].update(state=outcome, next_action=action, result_revision=2,
                                order_id=uuid4() if outcome == "closed" else None)
            return state["row"].copy() if "FOR UPDATE" in sql else stale
        writes.append(sql)
        state["row"].update(responsible_operator_id=args[1], next_action=args[2])
        return state["row"].copy()

    @asynccontextmanager
    async def transaction(_):
        yield SimpleNamespace(fetchrow=fetchrow)

    monkeypatch.setattr(module, "unit_of_work", transaction)
    result = await module.close(app, lot["id"], 999, "retry")
    assert len(reads) == 1 and "FOR UPDATE" in reads[0]
    assert result["status"] == outcome
    assert state["row"]["next_action"] == action
    assert len(writes) == (1 if outcome == "allocation_denied" else 0)
    for key in ("id", "winner_id", "response_due_at", "escalation_due_at"):
        assert state["row"][key] == original[key]
    assert state["row"]["result_revision"] == 2
    assert len(state["events"]) == len(state["transitions"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["bidding", "prebid_pending"])
async def test_assignment_and_deadlines_survive_retry(close_consumer, mode):
    module, app, lot, state, now = close_consumer
    lot["mode"] = mode
    await module.close(app, lot["id"], 1, "original")
    held = state["row"].copy()
    app.state.closing_operator_id = uuid4()
    await module.close(app, lot["id"], 999, "retry")
    assert state["row"] == held
    assert held["response_due_at"] == now + timedelta(hours=24)
    assert held["escalation_due_at"] == now + timedelta(hours=48)
    held.update(result_revision=1, next_attempt_at=now)
    result = module.recovery(held, "USD")
    assert result["responsible_operator_id"] == held["responsible_operator_id"]
    assert result["next_review_at"] == held["response_due_at"]
    assert result["next_action"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["bidding", "prebid_pending", "prebid_reserved"])
@pytest.mark.parametrize("assignment", [None, "invalid", "00000000-0000-0000-0000-000000000000"])
async def test_missing_assignment_persists_held_decision(close_consumer, mode, assignment):
    module, app, lot, state, now = close_consumer
    lot["mode"] = mode
    app.state.closing_operator_id = assignment
    first = await module.close(app, lot["id"], 1, "missing")
    held = state["row"].copy()
    assert held["responsible_operator_id"] is None
    assert held["next_action"]
    assert held["response_due_at"] == now + timedelta(hours=24)
    assert held["escalation_due_at"] == now + timedelta(hours=48)
    assert lot["mode"] == ("closed_winner" if mode == "bidding" else mode)
    held["result_revision"] = 1
    assert module.recovery(held, "USD")["assignment_required"] is True
    assert await module.close(app, lot["id"], 999, "retry") == first
    assert len(state["events"]) == 1
    app.state.closing_operator_id = uuid4()
    assert await module.close(app, lot["id"], 999, "assign") == first
    assert state["row"]["id"] == held["id"]
    assert state["row"]["responsible_operator_id"] == app.state.closing_operator_id
    assert state["row"]["response_due_at"] == held["response_due_at"]
    assert state["row"]["escalation_due_at"] == held["escalation_due_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("hours,events", [(47, 0), (48, 1), (49, 1)])
@pytest.mark.parametrize("assigned", [False, True])
async def test_overdue_escalation_once_without_changing_result(lane_modules, monkeypatch, hours, events, assigned):
    module = lane_modules("closing_follow_up", "services/auction/modules/closing/follow_up.py")
    start = datetime(2026, 11, 16, tzinfo=timezone.utc)
    row = dict(auction_id=uuid4(), id=uuid4(), responsible_operator_id=uuid4() if assigned else None,
               next_action="review_allocation_denial", response_due_at=start + timedelta(hours=24),
               escalation_due_at=start + timedelta(hours=48), escalated_at=None,
               state="allocation_denied", winner_id=uuid4(), result_revision=2)
    original = row.copy()
    notices = []

    async def fetch(sql):
        assert "escalation_due_at<=clock_timestamp()" in sql
        assert "escalated_at IS NULL" in sql
        assert "FOR UPDATE SKIP LOCKED" in sql
        assert "LIMIT 10" in sql
        if row["escalated_at"] is None and start + timedelta(hours=hours) >= row["escalation_due_at"]:
            row["escalated_at"] = start + timedelta(hours=hours)
            return [row.copy()]
        return []

    @asynccontextmanager
    async def transaction(_):
        yield SimpleNamespace(fetch=fetch)

    async def enqueue(tx, event, destinations):
        notices.append(event)

    monkeypatch.setattr(module, "unit_of_work", transaction)
    monkeypatch.setattr(module, "enqueue", enqueue)
    app = SimpleNamespace(state=SimpleNamespace(pool=None))
    await module.escalate_overdue(app)
    await module.escalate_overdue(app)
    assert len(notices) == events
    assert {k: v for k, v in row.items() if k != "escalated_at"} == {k: v for k, v in original.items() if k != "escalated_at"}
    if events:
        assert notices[0].data["operation_id"] == str(row["id"])
        assert notices[0].data["responsible_operator_id"] == (str(row["responsible_operator_id"]) if assigned else None)
        assert notices[0].data["assignment_required"] is (not assigned)


@pytest.mark.asyncio
async def test_failed_transaction_rolls_back_decision_and_transition(close_consumer, monkeypatch):
    module, app, lot, state, _ = close_consumer
    app.state.closing_operator_id = None
    original = lot.copy()

    async def unavailable(*args):
        raise RuntimeError('Unavailable')

    monkeypatch.setattr(module, 'enqueue', unavailable)
    with pytest.raises(RuntimeError):
        await module.close(app, lot['id'], 1, 'rollback')
    assert lot == original
    assert state['row'] is None
    assert not state['transitions']
    assert not state['events']
