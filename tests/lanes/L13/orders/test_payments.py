import asyncio
import json
import hmac
import hashlib
from uuid import UUID, uuid4
import asyncpg
import pytest
from bt_runtime.modules import discover
from pathlib import Path


def processor():
    import os

    return next(
        m
        for m in discover(Path(os.environ["BT_MODULES_PATH"]))
        if m.id == "L13.payments"
    ).load("processor.py:process")


async def payable(market, route="card", seller_type="private"):
    app, c, user, service, stock, exact, *_ = market
    buyer, auth = user()
    watch = await stock(seller_type=seller_type)
    quote = exact(watch, buyer)
    reserved = await c.post(
        "/v1/exact-reservations",
        json={"watch_id": watch["watch_id"], "quote_id": quote, "expected_revision": 1},
        headers={**auth, "Idempotency-Key": "reserve"},
    )
    assert reserved.status_code == 200, reserved.text
    assert reserved.json()["status"] == "succeeded", reserved.text
    order = await app.state.l13_acknowledge_notice(reserved.json()["order"])
    started = await c.post(
        f"/v1/orders/{order['id']}/payment-attempts",
        json={"route": route, "expected_revision": order["revision"]},
        headers={**auth, "Idempotency-Key": "start"},
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "succeeded", started.text
    return buyer, auth, watch, order, started.json()["attempt"]


def callback(attempt, **changes):
    return {
        k: attempt[k]
        for k in (
            "order_id",
            "buyer_id",
            "quote_id",
            "quote_revision",
            "route",
            "reference",
            "currency",
            "total_minor",
        )
    } | {
        "attempt_id": attempt["id"],
        "event_id": str(uuid4()),
        "outcome": "confirmed",
        "sequence": 1,
        **changes,
    }


async def deliver(c, body, signature=None):
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = (
        signature
        or hmac.new(
            b"synthetic-signing-secret-for-local-proofs-only", raw, hashlib.sha256
        ).hexdigest()
    )
    return await c.post(
        "/callbacks/v1/simulated",
        content=raw,
        headers={"Content-Type": "application/json", "X-BT-Signature": signature},
    )


async def test_signed_confirmation_transaction_invariants(market):
    from bt_contracts.orders.payments import PaymentCallback
    from bt_runtime.app.db import unit_of_work

    app, _, *_ = market
    *_, attempt = await payable(market)
    async with unit_of_work(app.state.pool) as tx:
        result = await processor()(
            tx,
            PaymentCallback.model_validate(callback(attempt)),
            "direct-transaction-proof",
        )
        assert result["paid"]


@pytest.mark.parametrize("route", ["card", "whish", "omt"])
async def test_exact_5150_posts_once_restart_replay_and_balanced(market, route):
    app, c, *_ = market
    _, auth, watch, order, attempt = await payable(market, route)
    body = callback(attempt)
    responses = await asyncio.gather(
        deliver(c, body),
        deliver(c, body),
        deliver(c, callback(attempt, event_id=str(uuid4()), sequence=2)),
    )
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert all(r.json()["paid"] for r in responses)
    assert await app.state.pool.fetchval("SELECT count(*) FROM l13_journal_groups") == 1
    assert (
        await app.state.pool.fetchval(
            "SELECT sum(amount_minor) FROM l13_journal_entries"
        )
        == 0
    )
    assert (
        await app.state.pool.fetchval(
            "SELECT count(*) FROM outbox WHERE envelope->>'type'='orders.payment-confirmed.v1'"
        )
        == 1
    )
    # No process-local receipt cache: a new HTTP client / pooled connection sees retained result.
    again = await deliver(c, body)
    assert again.json() == responses[0].json()
    result = await c.get("/v1/orders/" + order["id"] + "/checkout", headers=auth)
    assert result.json()["order"]["state"] == "paid_held"
    assert result.json()["quote"]["payable_minor"] == 515000
    timeline = await c.get("/v1/orders/" + order["id"], headers=auth)
    assert [entry["action"] for entry in timeline.json()["history"]] == [
        "reserve",
        "payment-notified",
        "payment-attempt",
        "payment-confirmed",
    ]
    from bt_contracts.orders.journal.facts import PaidOrderFact

    fact_response = await c.get(
        "/internal/v1/orders/" + order["id"] + "/paid-fact", headers=market[3]("trust")
    )
    assert fact_response.status_code == 200, fact_response.text
    fact = PaidOrderFact.model_validate(fact_response.json())
    assert fact.paid and fact.seller_type == "private" and not fact.payout_authorized
    late = await deliver(c, callback(attempt, outcome="declined", sequence=99))
    assert late.json()["paid"] is True
    assert (
        await app.state.pool.fetchval(
            "SELECT status FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])
        )
        == "reserved"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_minor", 515001),
        ("currency", "LBP"),
        ("reference", "SIM-wrong"),
        ("quote_id", str(uuid4())),
        ("quote_revision", 2),
        ("order_id", str(uuid4())),
        ("buyer_id", str(uuid4())),
        ("route", "omt"),
    ],
)
async def test_signed_wrong_binding_cannot_pay(market, field, value):
    app, c, *_ = market
    *_, attempt = await payable(market)
    response = await deliver(c, callback(attempt, **{field: value}))
    assert response.status_code == 409, response.text
    assert await app.state.pool.fetchval("SELECT count(*) FROM l13_journal_groups") == 0


async def test_forgery_invalid_route_and_missing_signing_fail_closed(
    market, monkeypatch
):
    app, c, *_ = market
    _, auth, _, order, attempt = await payable(market)
    assert (await deliver(c, callback(attempt), signature="0" * 64)).status_code == 401
    assert (await deliver(c, callback(attempt, route="wire"))).status_code == 422
    monkeypatch.delenv("BT_SIMULATED_PAYMENT_SECRET")
    assert (await deliver(c, callback(attempt))).status_code == 503
    assert await app.state.pool.fetchval("SELECT count(*) FROM l13_journal_groups") == 0


async def test_pending_declined_retry_and_old_attempt_cannot_post_twice(market):
    app, c, *_ = market
    _, auth, _, order, attempt = await payable(market)
    p = await deliver(c, callback(attempt, outcome="pending", sequence=2))
    assert p.json()["status"] == "pending"
    assert (
        await deliver(c, callback(attempt, outcome="confirmed", sequence=1))
    ).json()["paid"] is False
    assert (await deliver(c, callback(attempt, outcome="declined", sequence=3))).json()[
        "paid"
    ] is False
    detail = (
        await c.get("/v1/orders/" + order["id"] + "/checkout", headers=auth)
    ).json()
    new = await c.post(
        "/v1/orders/" + order["id"] + "/payment-attempts",
        headers={**auth, "Idempotency-Key": "retry"},
        json={"expected_revision": detail["order"]["revision"], "route": "omt"},
    )
    assert new.json()["attempt"]["id"] != attempt["id"], new.text
    old = await deliver(c, callback(attempt, sequence=4))
    assert old.json()["code"] == "reconciliation_required"
    done = await deliver(c, callback(new.json()["attempt"], sequence=1))
    assert done.json()["paid"] is True
    assert await app.state.pool.fetchval("SELECT count(*) FROM l13_journal_groups") == 1


async def test_manual_unknown_hold_never_starts_a_competing_attempt(market):
    app, c, user, service, stock, exact, *_ = market
    buyer, auth = user()
    watch = await stock()
    quote = exact(watch, buyer)
    reserved = await c.post(
        "/v1/exact-reservations",
        headers={**auth, "Idempotency-Key": "reserve-held"},
        json={"watch_id": watch["watch_id"], "quote_id": quote, "expected_revision": 1},
    )
    assert reserved.status_code == 200 and reserved.json()["status"] == "succeeded", reserved.text
    order = await app.state.l13_acknowledge_notice(reserved.json()["order"])
    manager, manager_auth = user(permissions=["orders.manage"])
    held = await c.post(
        "/v1/orders/" + order["id"] + "/transitions",
        headers={**manager_auth, "Idempotency-Key": "unknown-hold"},
        json={
            "expected_revision": order["revision"],
            "state": "payment_unknown",
            "reason": "Unknown financial result requires reconciliation",
        },
    )
    assert held.json()["status"] == "succeeded", held.text
    checkout = (
        await c.get("/v1/orders/" + order["id"] + "/checkout", headers=auth)
    ).json()
    assert checkout["payable"] is False
    result = await c.post(
        "/v1/orders/" + order["id"] + "/payment-attempts",
        headers={**auth, "Idempotency-Key": "held-start"},
        json={"expected_revision": checkout["order"]["revision"], "route": "card"},
    )
    assert result.json()["code"] == "reconciliation_required", result.text
    assert (
        await app.state.pool.fetchval("SELECT count(*) FROM l13_payment_attempts") == 0
    )


async def test_cross_buyer_private_reads_and_simulation_deny(market):
    app, c, user, *_ = market
    _, auth, _, order, attempt = await payable(market)
    _, stranger = user()
    for path in (
        "/v1/orders/" + order["id"] + "/checkout",
        "/v1/orders/" + order["id"] + "/journal",
    ):
        assert (await c.get(path, headers=stranger)).status_code == 403
    r = await c.post(
        "/v1/payment-attempts/" + attempt["id"] + "/simulate",
        headers={**stranger, "Idempotency-Key": "bad"},
        json={"outcome": "confirmed"},
    )
    assert r.status_code == 403, r.text
    first = await c.post(
        "/v1/payment-attempts/" + attempt["id"] + "/simulate",
        headers={**auth, "Idempotency-Key": "simulate"},
        json={"outcome": "confirmed"},
    )
    second = await c.post(
        "/v1/payment-attempts/" + attempt["id"] + "/simulate",
        headers={**auth, "Idempotency-Key": "simulate"},
        json={"outcome": "confirmed"},
    )
    assert first.json() == second.json()
    assert first.json()["paid"]


async def test_expired_unknown_result_holds_and_database_rejects_unbalanced(market):
    app, c, *_ = market
    *_, order, attempt = await payable(market)
    await app.state.pool.execute(
        "UPDATE l08_orders SET deadline=clock_timestamp()-interval '1 second' WHERE id=$1",
        UUID(order["id"]),
    )
    response = await deliver(c, callback(attempt))
    assert response.json()["code"] == "reconciliation_required"
    assert await app.state.pool.fetchval("SELECT count(*) FROM l13_journal_groups") == 0
    with pytest.raises(asyncpg.RaiseError, match="balanced|exact confirmed attempt"):
        async with app.state.pool.acquire() as tx:
            async with tx.transaction():
                await tx.execute(
                    "INSERT INTO l13_journal_groups(id,order_id,attempt_id,currency,total_minor) VALUES($1,$2,$3,'USD',515000)",
                    uuid4(),
                    UUID(order["id"]),
                    UUID(attempt["id"]),
                )
    with pytest.raises(asyncpg.RaiseError, match="Paid requires"):
        await app.state.pool.execute(
            "UPDATE l08_orders SET state='paid_held' WHERE id=$1", UUID(order["id"])
        )


async def test_business_journal_requires_current_selected_organization_even_for_creator(
    market,
):
    app, c, user, *_ = market
    _, buyer_auth, watch, order, _ = await payable(market, seller_type="dealer")
    _, personal_creator = user(subject=UUID(watch["seller_id"]))
    for suffix in ("", "/journal"):
        denied = await c.get(
            "/v1/orders/" + order["id"] + suffix, headers=personal_creator
        )
        assert denied.status_code == 403, denied.text
    # The individual buyer remains an actual party without selecting the seller's organization.
    assert (
        await c.get("/v1/orders/" + order["id"] + "/journal", headers=buyer_auth)
    ).status_code == 200
