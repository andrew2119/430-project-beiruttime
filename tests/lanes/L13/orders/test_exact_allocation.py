"""Orders binds current Pricing v3 authority to separately retained economics."""

import asyncio
from uuid import UUID, uuid4

import pytest

def allocation(watch, buyer, quote, source, kind, key, *, revision=1, total=515000):
    return {
        "operation_key": key, "watch_id": watch["watch_id"], "listing_id": watch["listing_id"],
        "listing_revision": watch["listing_revision"], "expected_revision": revision,
        "source_id": str(source), "kind": kind, "buyer_id": str(buyer), "quote_id": quote,
        "quote_revision": 1, "currency": "USD", "total_minor": total,
    }


async def auction_fence(c, service, watch, source, stages):
    revision = 1
    for stage in stages:
        result = await c.post(
            "/internal/v2/commitments",
            headers={**service("auction"), "Idempotency-Key": stage},
            json={"operation_key": stage, "watch_id": watch["watch_id"], "listing_id": watch["listing_id"],
                  "listing_revision": 1, "expected_revision": revision, "source_id": str(source),
                  "kind": stage, "reason": "Synthetic contract admission"},
        )
        assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
        revision = result.json()["watch"]["revision"]
    return revision


@pytest.mark.parametrize("kind", ["offer", "winner"])
async def test_guarded_allocation_retains_exact_quote_once(market, kind):
    app, c, user, service, stock, exact, quotes, validations = market
    buyer, auth = user()
    watch = await stock("fixed" if kind == "offer" else "auction")
    quote_id = exact(watch, buyer)
    source_id = uuid4()
    revision = 1
    if kind == "winner":
        quotes[quote_id]["reviewed_at"] = None
        revision = await auction_fence(c, service, watch, source_id, ["auction_open", "first_bid"])
    validations[quote_id] = app.state.l13_committed_quote(watch, buyer, quote_id, source_id, kind=kind)
    body = allocation(watch, buyer, quote_id, source_id, kind, "allocate", revision=revision)
    headers = {**service("pricing" if kind == "offer" else "auction"), "Idempotency-Key": "allocate"}
    outcomes = await asyncio.gather(*(
        c.post("/internal/v2/allocations", headers=headers, json=body) for _ in range(2)
    ))
    assert all(r.status_code == 200 for r in outcomes), [r.text for r in outcomes]
    assert outcomes[0].json() == outcomes[1].json()
    assert outcomes[0].json()["status"] == "succeeded", outcomes[0].text
    order = outcomes[0].json()["order"]
    order_id = UUID(order["id"])
    assert order["quote_id"] == quote_id and order["total_minor"] == 515000 and order["currency"] == "USD"
    assert order["state"] == "awaiting_notification" and order["payment_authority"] is False
    assert order["notified_at"] is None and order["deadline"] is None
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 1
    assert await app.state.pool.fetchval("SELECT quote_revision FROM l13_order_quotes WHERE order_id=$1", order_id) == 1
    assert await app.state.pool.fetchval("SELECT status FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])) == "reserved"
    assert set(app.state.l13_pricing_reads) == {("validation", quote_id), ("retained", quote_id)}
    assert await app.state.pool.fetchval(
        "SELECT count(*) FROM outbox WHERE envelope->>'type'='orders.payment-action-required.v3' AND envelope->>'subject'=$1",
        str(order_id),
    ) == 1
    if kind == "winner":
        denied_before_notice = await c.post(
            f"/v1/orders/{order_id}/payment-attempts",
            headers={**auth, "Idempotency-Key": "notice-not-delivered"},
            json={"route": "card", "expected_revision": order["revision"],
                  "quote_revision": 1, "total_minor": 515000, "currency": "USD"},
        )
        assert denied_before_notice.json()["code"] == "order_not_payable", denied_before_notice.text
        assert await app.state.pool.fetchval("SELECT count(*) FROM l13_payment_attempts") == 0
        order = await app.state.l13_acknowledge_notice(order)
        denied = await c.post(
            f"/v1/orders/{order_id}/payment-attempts",
            headers={**auth, "Idempotency-Key": "missing-review"},
            json={"route": "card", "expected_revision": order["revision"]},
        )
        assert denied.json()["code"] == "exact_quote_review_required", denied.text
        accepted = await c.post(
            f"/v1/orders/{order_id}/payment-attempts",
            headers={**auth, "Idempotency-Key": "reviewed-total"},
            json={"route": "card", "expected_revision": order["revision"],
                  "quote_revision": 1, "total_minor": 515000, "currency": "USD"},
        )
        assert accepted.json()["status"] == "succeeded", accepted.text
        assert await app.state.pool.fetchval("SELECT count(*) FROM l13_journal_groups") == 0
        confirm = await c.post(
            "/v1/payment-attempts/" + accepted.json()["attempt"]["id"] + "/simulate",
            headers={**auth, "Idempotency-Key": "signed-winner-payment"}, json={"outcome": "confirmed"},
        )
        assert confirm.json()["paid"] is True, confirm.text
        timeline = await c.get(f"/v1/orders/{order_id}", headers=auth)
        assert [entry["action"] for entry in timeline.json()["history"]] == [
            "allocate", "payment-notified", "payment-attempt", "payment-confirmed",
        ]


@pytest.mark.parametrize("kind,caller,code", [
    ("prebid", "auction", "auction_purchase_removed"),
    ("brand_job", "orders", "typed_job_binding_required"),
])
async def test_legacy_allocation_shapes_cannot_create_a_new_order(market, kind, caller, code):
    app, c, user, service, stock, exact, _, _ = market
    buyer, _ = user()
    watch = await stock("auction" if kind == "prebid" else "fixed")
    source = uuid4()
    revision = await auction_fence(c, service, watch, source, ["auction_open"]) if kind == "prebid" else 1
    quote_id = exact(watch, buyer)
    before = await app.state.pool.fetchrow("SELECT * FROM l08_watches WHERE id=$1", UUID(watch["watch_id"]))
    body = allocation(watch, buyer, quote_id, source, kind, "legacy-allocation", revision=revision)
    headers = {**service(caller), "Idempotency-Key": body["operation_key"]}
    for _ in range(2):
        response = await c.post("/internal/v2/allocations", headers=headers, json=body)
        assert response.status_code == 200 and response.json() == {"status": "denied", "code": code}, response.text
    assert app.state.l13_pricing_reads == []
    assert await app.state.pool.fetchrow("SELECT * FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])) == before
    for table in ("l08_orders", "l13_order_quotes", "l13_payment_notices", "l13_payment_attempts", "l13_journal_groups"):
        assert await app.state.pool.fetchval(f"SELECT count(*) FROM {table}") == 0


async def test_client_amount_is_not_quote_authority(market):
    app, c, user, service, stock, exact, _, validations = market
    buyer, _ = user()
    watch = await stock()
    quote_id = exact(watch, buyer)
    source = uuid4()
    validations[quote_id] = app.state.l13_committed_quote(watch, buyer, quote_id, source)
    body = allocation(watch, buyer, quote_id, source, "offer", "wrong-amount", total=515001)
    response = await c.post("/internal/v2/allocations", headers={**service("pricing"), "Idempotency-Key": "wrong-amount"}, json=body)
    assert response.status_code == 409 and response.json()["error"]["code"] == "quote_binding_mismatch", response.text
    assert app.state.l13_pricing_reads == [("validation", quote_id)]
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 0


@pytest.mark.parametrize("mutation", [
    {"authority": "payment_authority"}, {"payable_minor": 515001}, {"seller_net_minor": 475001},
    {"source_revision": 2}, {"quote_revision": 2}, {"buyer_id": "00000000-0000-4000-8000-000000000001"},
    {"selected_line_ids": ["00000000-0000-4000-8000-000000000001"]}, {"terms_digest": "unaccepted-terms"},
    {"diagnosis": "Private assessment must never be retained by Orders"},
])
async def test_retained_history_never_overrides_current_exact_binding(market, mutation):
    app, c, user, service, stock, exact, _, validations = market
    buyer, _ = user()
    watch = await stock()
    quote_id = exact(watch, buyer)
    source = uuid4()
    validations[quote_id] = app.state.l13_committed_quote(watch, buyer, quote_id, source)
    app.state.l13_retained_overrides[quote_id] = mutation
    body = allocation(watch, buyer, quote_id, source, "offer", "bad-retention")
    response = await c.post(
        "/internal/v2/allocations", headers={**service("pricing"), "Idempotency-Key": body["operation_key"]}, json=body,
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "quote_binding_mismatch"
    assert app.state.l13_pricing_reads == [("validation", quote_id), ("retained", quote_id)]
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 0
    assert await app.state.pool.fetchval("SELECT status FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])) == "available"


async def test_historical_preview_expiry_cannot_override_committed_economics(market):
    app, c, user, service, stock, exact, _, validations = market
    buyer, _ = user()
    watch = await stock()
    quote_id = exact(watch, buyer)
    source = uuid4()
    validations[quote_id] = app.state.l13_committed_quote(watch, buyer, quote_id, source)
    app.state.l13_retained_overrides[quote_id] = {"expires_at": "2000-01-01T00:00:00Z"}
    body = allocation(watch, buyer, quote_id, source, "offer", "historical-preview")
    response = await c.post(
        "/internal/v2/allocations", headers={**service("pricing"), "Idempotency-Key": body["operation_key"]}, json=body,
    )
    assert response.status_code == 200 and response.json()["status"] == "succeeded", response.text
    order = response.json()["order"]
    assert order["state"] == "awaiting_notification" and order["deadline"] is None and order["payment_authority"] is False
    history = await app.state.pool.fetchrow(
        """SELECT snapshot->>'expires_at' AS preview,
        snapshot->'authorization_expires_at'='null'::jsonb AS no_price_deadline
        FROM l13_order_quotes WHERE order_id=$1""",
        UUID(order["id"]),
    )
    assert history["preview"].startswith("2000-01-01") and history["no_price_deadline"] is True
