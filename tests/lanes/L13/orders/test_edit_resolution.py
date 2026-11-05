"""Exact retained Catalog edit resolution; never a cross-producer status oracle."""

from uuid import UUID, uuid4
import asyncpg
import pytest


def edit(watch, *, revision=1, source=None, kind="edit"):
    return {
        "operation_key": "catalog-edit",
        "watch_id": watch["watch_id"],
        "listing_id": watch["listing_id"],
        "listing_revision": 1,
        "expected_revision": revision,
        "source_id": str(source or uuid4()),
        "kind": kind,
        "reason": "Private seller note must not be disclosed",
    }


async def send(c, service, body):
    return await c.post(
        "/internal/v2/commitments",
        headers={**service("catalog"), "Idempotency-Key": body["operation_key"]},
        json=body,
    )


async def resolution(c, service, body, caller="auction"):
    return await c.get(
        "/internal/v2/listing-edit-operations/" + body["source_id"],
        params={"operation_key": body["operation_key"]},
        headers=service(caller),
    )


@pytest.mark.parametrize("expected_revision,status", [(1, "succeeded"), (2, "denied")])
async def test_resolution_is_exact_read_only_and_minimal(
    market, expected_revision, status
):
    app, c, user, service, stock, *_ = market
    watch = await stock()
    body = edit(watch, revision=expected_revision)
    result = await send(c, service, body)
    assert result.json()["status"] == status, result.text
    before = dict(
        await app.state.pool.fetchrow(
            "SELECT * FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])
        )
    )
    count = await app.state.pool.fetchval("SELECT count(*) FROM l08_audit")
    for _ in range(2):
        read = await resolution(c, service, body)
        assert read.status_code == 200, read.text
        assert read.json() == {
            "id": result.json()["id"],
            "operation_key": body["operation_key"],
            "producer": "catalog",
            "kind": "edit",
            "source_id": body["source_id"],
            "watch_id": watch["watch_id"],
            "listing_id": watch["listing_id"],
            "listing_revision": 1,
            "expected_revision": expected_revision,
            "status": status,
        }
        assert "reason" not in read.text and "request_id" not in read.text
    assert (
        dict(
            await app.state.pool.fetchrow(
                "SELECT * FROM l08_watches WHERE id=$1", UUID(watch["watch_id"])
            )
        )
        == before
    )
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_audit") == count
    # Generic operation lookup remains producer-private.
    assert (
        await c.get(
            "/internal/v2/operations/" + body["operation_key"],
            headers=service("auction"),
        )
    ).status_code == 404
    assert (
        await c.get(
            "/internal/v2/operations/" + body["operation_key"],
            headers=service("catalog"),
        )
    ).json() == result.json()
    with pytest.raises(asyncpg.RaiseError, match="immutable"):
        await app.state.pool.execute(
            "UPDATE l13_listing_edit_bindings SET expected_revision=99 WHERE operation_id=$1",
            UUID(result.json()["id"]),
        )


async def test_resolution_rejects_wrong_producer_source_key_kind_and_user(market):
    app, c, user, service, stock, *_ = market
    watch = await stock()
    body = edit(watch)
    assert (await send(c, service, body)).json()["status"] == "succeeded"
    for caller in ("catalog", "pricing", "orders"):
        assert (await resolution(c, service, body, caller)).status_code == 403
    _, auth = user()
    path = "/internal/v2/listing-edit-operations/" + body["source_id"]
    assert (
        await c.get(path, params={"operation_key": body["operation_key"]}, headers=auth)
    ).status_code == 401
    assert (
        await c.get(path, params={"operation_key": body["operation_key"]})
    ).status_code == 401
    assert (
        await resolution(c, service, {**body, "source_id": str(uuid4())})
    ).status_code == 404
    assert (
        await resolution(c, service, {**body, "operation_key": "another-operation"})
    ).status_code == 404
    other = await stock()
    withdraw = edit(other, kind="withdraw")
    withdraw["operation_key"] = "catalog-withdraw"
    assert (await send(c, service, withdraw)).json()["status"] == "succeeded"
    assert (await resolution(c, service, withdraw)).status_code == 404
    assert (
        await app.state.pool.fetchval("SELECT count(*) FROM l13_listing_edit_bindings")
        == 1
    )


async def test_legacy_receipt_is_backfilled_only_by_exact_original_command_replay(
    market, monkeypatch
):
    app, c, user, service, stock, *_ = market
    watch = await stock()
    body = edit(watch)
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/internal/v2/commitments"
    )
    original = endpoint.__globals__["command"]

    async def legacy(*args, **kwargs):
        kwargs.pop("retain_result", None)
        return await original(*args, **kwargs)

    monkeypatch.setitem(endpoint.__globals__, "command", legacy)
    first = await send(c, service, body)
    assert first.json()["status"] == "succeeded"
    monkeypatch.setitem(endpoint.__globals__, "command", original)
    assert (await resolution(c, service, body)).status_code == 404
    changed = await send(c, service, {**body, "expected_revision": 2})
    assert changed.status_code == 409
    assert (await resolution(c, service, body)).status_code == 404
    audits = await app.state.pool.fetchval("SELECT count(*) FROM l08_audit")
    replay = await send(c, service, body)
    assert replay.json() == first.json()
    read = await resolution(c, service, body)
    assert read.status_code == 200 and read.json()["id"] == first.json()["id"]
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_audit") == audits
    assert (
        await app.state.pool.fetchval(
            "SELECT count(*) FROM l08_operations WHERE actor_key='service:catalog' AND idempotency_key=$1",
            body["operation_key"],
        )
        == 1
    )
