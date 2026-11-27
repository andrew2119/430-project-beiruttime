import asyncio
from uuid import uuid4, UUID


async def execute(c, service, watch, kind, source, revision, key, caller="auction"):
    body = {
        "operation_key": key,
        "watch_id": watch["watch_id"],
        "listing_id": watch["listing_id"],
        "listing_revision": 1,
        "expected_revision": revision,
        "source_id": str(source),
        "kind": kind,
        "reason": "Synthetic guarded race proof",
    }
    return await c.post(
        "/internal/v2/commitments",
        json=body,
        headers={**service(caller), "Idempotency-Key": key},
    )


async def test_withdraw_against_first_bid_has_one_winner(market):
    app, c, user, service, stock, *_ = market
    watch = await stock("auction")
    auction = uuid4()
    opened = await execute(c, service, watch, "auction_open", auction, 1, "open")
    assert opened.json()["watch"]["auction_committed"] is False, opened.text
    results = await asyncio.gather(
        execute(c, service, watch, "first_bid", auction, 2, "bid"),
        execute(c, service, watch, "withdraw", uuid4(), 2, "withdraw", "catalog"),
    )
    assert sorted(r.json()["status"] for r in results) == ["denied", "succeeded"], [
        r.text for r in results
    ]
    state = await c.get(
        "/internal/v2/watches/" + watch["watch_id"], headers=service("catalog")
    )
    assert state.json()["status"] in ("withdrawn", "fenced")
    persisted = await c.get(
        "/internal/v2/operations/withdraw", headers=service("catalog")
    )
    assert persisted.json()["status"] == results[1].json()["status"]
    assert (
        await c.get("/internal/v2/operations/withdraw", headers=service("auction"))
    ).status_code == 404


async def test_purchase_versus_withdraw_serializes_and_retains_history(market):
    app, c, user, service, stock, exact, *_ = market
    watch = await stock()
    buyer, auth = user()
    quote = exact(watch, buyer)
    results = await asyncio.gather(
        c.post(
            "/v1/exact-reservations",
            json={
                "watch_id": watch["watch_id"],
                "quote_id": quote,
                "expected_revision": 1,
            },
            headers={**auth, "Idempotency-Key": "reserve"},
        ),
        execute(c, service, watch, "withdraw", uuid4(), 1, "withdraw", "catalog"),
    )
    assert sorted(r.json()["status"] for r in results) == ["denied", "succeeded"], [
        r.text for r in results
    ]
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_watches") == 1
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_audit") >= 2


async def test_edit_fence_cannot_release_by_timeout_or_wrong_source(market):
    app, c, user, service, stock, *_ = market
    watch = await stock()
    source = uuid4()
    edit = await execute(c, service, watch, "edit", source, 1, "edit", "catalog")
    assert edit.json()["status"] == "succeeded"
    body = {
        "operation_key": "finish-wrong",
        "source_id": str(uuid4()),
        "listing_revision": 2,
    }
    denied = await c.post(
        "/internal/v2/watches/" + watch["watch_id"] + "/edit-complete",
        headers={**service("catalog"), "Idempotency-Key": "finish-wrong"},
        json=body,
    )
    assert denied.json()["status"] == "denied"
    assert (
        await app.state.pool.fetchval(
            "SELECT status FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])
        )
        == "editing"
    )
    body = {"operation_key": "finish", "source_id": str(source), "listing_revision": 2}
    success = await c.post(
        "/internal/v2/watches/" + watch["watch_id"] + "/edit-complete",
        headers={**service("catalog"), "Idempotency-Key": "finish"},
        json=body,
    )
    assert success.json()["watch"]["listing_revision"] == 2


async def test_v1_fence_remains_conservatively_committed(market):
    app, c, user, service, stock, *_ = market
    watch = await stock("auction")
    source = uuid4()
    fenced = await c.post(
        "/internal/v1/watches/" + watch["watch_id"] + "/fences",
        headers={**service("auction"), "Idempotency-Key": "legacy"},
        json={
            "source_id": str(source),
            "expected_revision": 1,
            "reason": "Legacy auction fence",
        },
    )
    assert fenced.json()["status"] == "succeeded"
    result = await execute(
        c, service, watch, "withdraw", uuid4(), 2, "withdraw", "catalog"
    )
    assert result.json()["code"] == "watch_committed"
