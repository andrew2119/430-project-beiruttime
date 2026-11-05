"""Provider fixture matches published CurrentQuote and flat RetainedFinancialQuote v2."""

from uuid import UUID, uuid4
import asyncio
import pytest


@pytest.mark.parametrize("kind", ["offer", "prebid", "winner", "brand_job"])
async def test_guarded_allocation_retains_exact_quote_once(market, kind):
    app, c, user, service, stock, exact, quotes, validations = market
    buyer, auth = user()
    watch = await stock("fixed" if kind in {"offer", "brand_job"} else "auction")
    quote_id = exact(watch, buyer)
    if kind == "winner":
        quotes[quote_id]["reviewed_at"] = None
    source_id = str(uuid4())
    revision = 1
    if kind not in {"offer", "brand_job"}:
        for stage in (
            ["auction_open", "first_bid"] if kind == "winner" else ["auction_open"]
        ):
            key = stage
            result = await c.post(
                "/internal/v2/commitments",
                headers={**service("auction"), "Idempotency-Key": key},
                json={
                    "operation_key": key,
                    "watch_id": watch["watch_id"],
                    "listing_id": watch["listing_id"],
                    "listing_revision": 1,
                    "expected_revision": revision,
                    "source_id": source_id,
                    "kind": stage,
                    "reason": "Synthetic contract admission",
                },
            )
            assert result.json()["status"] == "succeeded", result.text
            revision = result.json()["watch"]["revision"]
    validations[quote_id] = {
        "quote_id": quote_id,
        "quote_revision": 1,
        "buyer_id": str(buyer),
        "source_id": source_id,
        "source_revision": 2 if kind == "offer" else 1,
        "listing_id": watch["listing_id"],
        "listing_revision": 1,
        "kind": "brand" if kind == "brand_job" else kind,
        "currency": "USD",
        "total_minor": 515000,
        "expires_at": quotes[quote_id]["expires_at"],
        "status": "valid",
        "schedule_id": "sample-v1",
        "policy_revision": 1,
        "rounding": "half_up",
    }
    body = {
        "operation_key": "allocate",
        "watch_id": watch["watch_id"],
        "listing_id": watch["listing_id"],
        "listing_revision": 1,
        "expected_revision": revision,
        "source_id": source_id,
        "kind": kind,
        "buyer_id": str(buyer),
        "quote_id": quote_id,
        "quote_revision": 1,
        "currency": "USD",
        "total_minor": 515000,
    }
    headers = {
        **service(
            "pricing"
            if kind == "offer"
            else "orders"
            if kind == "brand_job"
            else "auction"
        ),
        "Idempotency-Key": "allocate",
    }
    outcomes = await asyncio.gather(
        *(
            c.post("/internal/v2/allocations", headers=headers, json=body)
            for _ in range(2)
        )
    )
    assert all(r.status_code == 200 for r in outcomes), [r.text for r in outcomes]
    assert outcomes[0].json() == outcomes[1].json()
    assert outcomes[0].json()["status"] == "succeeded", outcomes[0].text
    order_id = UUID(outcomes[0].json()["order"]["id"])
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 1
    assert (
        await app.state.pool.fetchval(
            "SELECT quote_revision FROM l13_order_quotes WHERE order_id=$1", order_id
        )
        == 1
    )
    assert (
        await app.state.pool.fetchval(
            "SELECT status FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])
        )
        == "reserved"
    )
    if kind == "winner":
        denied = await c.post(
            f"/v1/orders/{order_id}/payment-attempts",
            headers={**auth, "Idempotency-Key": "missing-review"},
            json={"route": "card", "expected_revision": 1},
        )
        assert denied.json()["code"] == "exact_quote_review_required", denied.text
        accepted = await c.post(
            f"/v1/orders/{order_id}/payment-attempts",
            headers={**auth, "Idempotency-Key": "reviewed-total"},
            json={
                "route": "card",
                "expected_revision": 1,
                "quote_revision": 1,
                "total_minor": 515000,
                "currency": "USD",
            },
        )
        assert accepted.json()["status"] == "succeeded", accepted.text
        assert (
            await app.state.pool.fetchval("SELECT count(*) FROM l13_journal_groups")
            == 0
        )
        confirm = await c.post(
            "/v1/payment-attempts/" + accepted.json()["attempt"]["id"] + "/simulate",
            headers={**auth, "Idempotency-Key": "signed-winner-payment"},
            json={"outcome": "confirmed"},
        )
        assert confirm.json()["paid"] is True, confirm.text
        timeline = await c.get(f"/v1/orders/{order_id}", headers=auth)
        assert [entry["action"] for entry in timeline.json()["history"]] == [
            "allocate",
            "payment-attempt",
            "payment-confirmed",
        ]


async def test_client_amount_is_not_quote_authority(market):
    app, c, user, service, stock, exact, quotes, validations = market
    buyer, _ = user()
    watch = await stock()
    id = exact(watch, buyer)
    source = str(uuid4())
    validations[id] = {
        "quote_id": id,
        "buyer_id": str(buyer),
        "source_id": source,
        "source_revision": 1,
        "schedule_id": "sample-v1",
        "policy_revision": 1,
        "rounding": "half_up",
        "listing_id": watch["listing_id"],
        "listing_revision": 1,
        "quote_revision": 1,
        "kind": "offer",
        "currency": "USD",
        "total_minor": 515000,
        "status": "valid",
        "expires_at": quotes[id]["expires_at"],
    }
    body = {
        "operation_key": "wrong-amount",
        "watch_id": watch["watch_id"],
        "listing_id": watch["listing_id"],
        "listing_revision": 1,
        "expected_revision": 1,
        "source_id": source,
        "kind": "offer",
        "buyer_id": str(buyer),
        "quote_id": id,
        "quote_revision": 1,
        "currency": "USD",
        "total_minor": 515001,
    }
    response = await c.post(
        "/internal/v2/allocations",
        headers={**service("pricing"), "Idempotency-Key": "wrong-amount"},
        json=body,
    )
    assert response.status_code == 409, response.text
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 0


@pytest.mark.parametrize(
    "mutation",
    [
        {"authority": "payment_authority"},
        {"payable_minor": 515001},
        {"seller_net_minor": 475001},
        {"source_revision": 2},
        {"quote_revision": 2},
        {"buyer_id": "00000000-0000-4000-8000-000000000001"},
        {"selected_line_ids": ["00000000-0000-4000-8000-000000000001"]},
        {"terms_digest": "unaccepted-terms"},
        {"diagnosis": "Private assessment must never be retained by Orders"},
        {"expires_at": "2000-01-01T00:00:00Z"},
    ],
)
async def test_retained_history_never_overrides_current_exact_binding(market, mutation):
    app, c, user, service, stock, exact, quotes, validations = market
    buyer, _ = user()
    watch = await stock()
    quote_id = exact(watch, buyer)
    source = str(uuid4())
    validations[quote_id] = {
        "quote_id": quote_id,
        "quote_revision": 1,
        "buyer_id": str(buyer),
        "source_id": source,
        "source_revision": 1,
        "listing_id": watch["listing_id"],
        "listing_revision": 1,
        "kind": "offer",
        "currency": "USD",
        "total_minor": 515000,
        "expires_at": quotes[quote_id]["expires_at"],
        "status": "valid",
        "schedule_id": "sample-v1",
        "policy_revision": 1,
        "rounding": "half_up",
    }
    app.state.l13_retained_overrides[quote_id] = mutation
    body = {
        "operation_key": "bad-retention",
        "watch_id": watch["watch_id"],
        "listing_id": watch["listing_id"],
        "listing_revision": 1,
        "expected_revision": 1,
        "source_id": source,
        "kind": "offer",
        "buyer_id": str(buyer),
        "quote_id": quote_id,
        "quote_revision": 1,
        "currency": "USD",
        "total_minor": 515000,
    }
    response = await c.post(
        "/internal/v2/allocations",
        headers={**service("pricing"), "Idempotency-Key": body["operation_key"]},
        json=body,
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "quote_binding_mismatch"
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 0
    assert (
        await app.state.pool.fetchval(
            "SELECT status FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])
        )
        == "available"
    )
