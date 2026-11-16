"""Isolated processor checks; real database races/constraints are still deferred."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from bt_contracts_core.errors import PublicError


@pytest.fixture
def payment_processor(lane_modules, monkeypatch):
    monkeypatch.setenv("BT_SIMULATED_PAYMENT_SECRET", "synthetic-signing-secret-for-local-proofs-only")
    module = lane_modules("lane_payment_processor", "services/orders/modules/payments/processor.py")
    now = datetime.now(timezone.utc)
    order = {"id": uuid4(), "watch_id": uuid4(), "listing_id": uuid4(), "buyer_id": uuid4(),
             "seller_id": uuid4(), "organization_id": None, "quote_id": uuid4(), "currency": "USD",
             "total_minor": 515000, "revision": 2, "state": "payment_unknown",
             "deadline": now + timedelta(hours=24)}
    attempt = {key: order[key] for key in ("buyer_id", "quote_id", "currency", "total_minor")} | {
        "id": uuid4(), "order_id": order["id"], "quote_revision": 1, "route": "card",
        "reference": "SIM-synthetic", "state": "pending", "sequence": 0, "created_at": now,
    }
    state = {"pricing_state": None, "newer": False, "callbacks": {}, "journals": [], "entries": [], "events": [], "locks": []}

    async def fetchrow(sql, *args):
        if sql.startswith("SELECT * FROM l13_payment_callbacks"):
            return state["callbacks"].get(args[0])
        if sql.startswith("SELECT * FROM l08_orders"):
            state["locks"].append("order")
            assert "FOR UPDATE" in sql
            return order
        if sql.startswith("SELECT * FROM l13_payment_attempts"):
            if "FOR UPDATE" in sql:
                state["locks"].append("attempt")
            return attempt
        if sql.startswith("UPDATE l08_orders SET state='paid_held'"):
            order.update(state="paid_held", revision=order["revision"] + 1)
            return order
        if sql.startswith("UPDATE l13_payment_attempts"):
            attempt.update(state=args[1], sequence=args[2])
            return attempt
        raise AssertionError(sql)

    async def fetchval(sql, *args):
        if sql == "SELECT clock_timestamp()":
            return now
        if sql.startswith("SELECT state FROM l13_quote_commitments"):
            return state["pricing_state"]
        if sql.startswith("SELECT 1 FROM l13_payment_attempts"):
            return state["newer"]
        raise AssertionError(sql)

    async def execute(sql, *args):
        if "pg_advisory_xact_lock" in sql:
            state["locks"].append("callback")
        elif sql.lstrip().startswith("INSERT INTO l13_journal_groups"):
            state["journals"].append(args)
        elif sql.startswith("INSERT INTO l13_payment_callbacks"):
            state["callbacks"][args[0]] = {"digest": args[2], "outcome": json.loads(args[3])}
        elif sql.startswith("UPDATE l08_orders"):
            order.update(state="payment_unknown", revision=order["revision"] + 1)
        elif not sql.startswith("INSERT INTO l08_audit"):
            raise AssertionError(sql)

    async def executemany(sql, rows):
        assert sql.startswith("INSERT INTO l13_journal_entries")
        state["entries"].extend(rows)

    async def enqueue(tx, event, destinations):
        state["events"].append(event)

    monkeypatch.setattr(module, "enqueue", enqueue)
    tx = SimpleNamespace(fetchrow=fetchrow, fetchval=fetchval, execute=execute, executemany=executemany)

    def body(**changes):
        return module.PaymentCallback(event_id=uuid4(), attempt_id=attempt["id"],
            **({key: attempt[key] for key in ("order_id", "buyer_id", "quote_id", "quote_revision",
                "route", "reference", "currency", "total_minor")} | {"outcome": "confirmed", "sequence": 1} | changes))

    return module, tx, order, attempt, state, body, now


@pytest.mark.asyncio
async def test_exact_signed_confirmation_replays_one_balanced_group(payment_processor):
    module, tx, order, attempt, state, body, _ = payment_processor
    callback = body()
    raw = callback.model_dump_json().encode()
    verified = module.verify(raw, module.sign(raw))
    first = await module.process(tx, verified, "confirmation")
    assert first["paid"] and order["state"] == "paid_held"
    assert await module.process(tx, verified, "duplicate") == first
    reordered = await module.process(tx, body(outcome="declined", sequence=99), "late")
    assert reordered["paid"] and attempt["state"] == "confirmed"
    assert len(state["journals"]) == len(state["events"]) == 1
    assert sum(entry[2] for entry in state["entries"]) == 0
    assert {entry[2] for entry in state["entries"]} == {515000, -515000}
    assert state["locks"][:3] == ["callback", "order", "attempt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("buyer_id", uuid4()), ("order_id", uuid4()),
    ("quote_id", uuid4()), ("quote_revision", 2), ("route", "omt"), ("reference", "SIM-other"),
    ("currency", "LBP"), ("total_minor", 515001)])
async def test_signed_mismatched_result_cannot_post(payment_processor, field, value):
    module, tx, order, attempt, state, body, _ = payment_processor
    with pytest.raises(PublicError, match="callback_binding_mismatch"):
        await module.process(tx, body(**{field: value}), "mismatch")
    assert not state["journals"] and not state["events"]
    assert order["state"] == "payment_unknown" and attempt["state"] == "pending"


@pytest.mark.asyncio
async def test_duplicate_event_with_changed_content_is_conflict(payment_processor):
    module, tx, _, _, state, body, _ = payment_processor
    first = body(outcome="pending")
    await module.process(tx, first, "pending")
    with pytest.raises(PublicError, match="callback_conflict"):
        await module.process(tx, first.model_copy(update={"outcome": "confirmed"}), "conflict")
    assert not state["journals"]


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-1, 0, 1])
async def test_before_equal_after_deadline_has_no_late_cash_post(payment_processor, offset):
    module, tx, order, attempt, state, body, now = payment_processor
    order["deadline"] = now + timedelta(seconds=offset)
    result = await module.process(tx, body(), "boundary")
    assert result["paid"] is (offset > 0)
    assert len(state["journals"]) == int(offset > 0)
    assert attempt["state"] == ("confirmed" if offset > 0 else "held")


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["newer", "expired_released", "expired_fenced", "declined"])
async def test_unknown_or_late_money_cannot_create_second_sale(payment_processor, conflict):
    module, tx, order, attempt, state, body, _ = payment_processor
    if conflict == "newer":
        state["newer"] = True
    elif conflict == "declined":
        attempt["state"] = "declined"
    else:
        order["state"] = conflict
    result = await module.process(tx, body(), "late-money")
    assert result["code"] == "reconciliation_required"
    assert not result["paid"] and not state["journals"]
    assert len(state["callbacks"]) == 1


@pytest.mark.asyncio
async def test_known_pricing_refusal_holds_signed_money_without_posting(payment_processor):
    module, tx, order, attempt, state, body, _ = payment_processor
    state["pricing_state"] = "reconciliation"
    result = await module.process(tx, body(), "pricing-hold")
    assert result["code"] == "reconciliation_required"
    assert not result["paid"] and not state["journals"]
    assert attempt["state"] == "held" and order["state"] == "payment_unknown"


def test_signed_bytes_are_required_and_unknown_fields_rejected(payment_processor):
    module, _, _, _, _, body, _ = payment_processor
    raw = body().model_dump_json().encode()
    with pytest.raises(PublicError, match="signature_invalid"):
        module.verify(raw, "0" * 64)
    changed = raw[:-1] + b',"real_payment":true}'
    with pytest.raises(PublicError, match="callback_invalid"):
        module.verify(changed, module.sign(changed))
    with pytest.raises(PublicError, match="callback_too_large"):
        module.verify(b"x" * 8193, "0" * 64)
