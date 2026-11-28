"""Kernel close unit proofs use real create/bid operations and deterministic server clock.
Orders/Pricing fixtures exercise wire/replay only; connected proof is recorded separately.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
import httpx
import pytest
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import create_pool
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from service_app.main import create_app
from service_app.dependencies import Dependencies
import service_app.kernel as kernel


@pytest_asyncio.fixture
async def auction(database_url):
    seller, buyer, other, listing, watch = [uuid4() for _ in range(5)]
    quotes = {}
    source = {"auction": None, "committed": False}
    operations = {}

    def watch_fact():
        return {
            "watch_id": str(watch),
            "listing_id": str(listing),
            "revision": 3 if source["committed"] else 2 if source["auction"] else 1,
            "listing_revision": 1,
            "source_id": source["auction"],
            "auction_committed": source["committed"],
            "status": "fenced" if source["auction"] else "available",
            "sale_mode": "auction",
            "source_matches": True,
        }

    def upstream(request):
        if request.url.host == "identity":
            id = request.headers.get("Authorization", "").removeprefix("Bearer ")
            return httpx.Response(
                200,
                json={
                    "actor": {"subject_id": id, "session_id": "synthetic"},
                    "roles": ["buyer", "private_seller"],
                    "permissions": ["identity.listings.publish"],
                    "organizations": [],
                    "organization_grants": [],
                },
            )
        if request.url.host == "catalog":
            return httpx.Response(
                200,
                json={
                    "id": str(listing),
                    "revision": 1,
                    "physical_watch_id": str(watch),
                    "seller_id": str(seller),
                    "organization_id": None,
                    "registration": {
                        "watch_id": str(watch),
                        "listing_id": str(listing),
                        "sale_mode": "auction",
                        "revision": 1,
                    },
                    "facts": {"sale_mode": "auction"},
                    "status": "published",
                },
            )
        if request.url.host == "orders":
            if request.method == "POST":
                body = json.loads(request.content)
                source["auction"] = body["source_id"]
                if body.get("kind") == "first_bid":
                    source["committed"] = True
                outcome = {
                    "id": str(uuid4()),
                    "request_id": "synthetic-operation",
                    "status": "succeeded",
                    "resource_id": str(watch),
                    "watch": watch_fact(),
                }
                operations[
                    body.get("operation_key", request.headers.get("idempotency-key"))
                ] = outcome
                return httpx.Response(200, json=outcome)
            if request.url.path.startswith("/internal/v2/operations/"):
                result = operations.get(request.url.path.rsplit("/", 1)[-1])
                return (
                    httpx.Response(200, json=result) if result else httpx.Response(404)
                )
            return httpx.Response(200, json=watch_fact())
        return httpx.Response(200, json=quotes[request.url.path.split("/")[-1]])

    dependencies = Dependencies(
        {
            n: DependencyClient(
                n, "http://" + n, transport=httpx.MockTransport(upstream)
            )
            for n in ("identity", "catalog", "pricing", "orders")
        },
        service_key="synthetic",
    )
    # Fence auth transport is intentionally injected; runtime service credentials remain mandatory.
    dependencies.service_headers = lambda *_: {
        "Authorization": "Bearer synthetic-service"
    }
    app = create_app(Settings(database_url=database_url), dependencies)
    app.state.pool = await create_pool(database_url)
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://auction"
    )

    async def open_lot(reserve=None):
        now = datetime.now(timezone.utc)
        result = await c.post(
            "/v1/auctions",
            headers={
                "Authorization": "Bearer " + str(seller),
                "Idempotency-Key": "create",
            },
            json={
                "listing_id": str(listing),
                "currency": "USD",
                "opening_minor": 400000,
                "reserve_minor": reserve,
                "increment_bands": [{"from_minor": 0, "step_minor": 10000}],
                "starts_at": (now - timedelta(minutes=1)).isoformat(),
                "ends_at": (now + timedelta(minutes=5)).isoformat(),
            },
        )
        assert result.status_code == 200, result.text
        return UUID(result.json()["auction_id"])

    async def bid(id, amount=500000):
        q = str(uuid4())
        now = datetime.now(timezone.utc)
        quotes[q] = {
            "id": q,
            "owner_id": str(buyer),
            "subject_id": str(id),
            "subject_revision": 1,
            "revision": 1,
            "purpose": "bid",
            "currency": "USD",
            "price_minor": amount,
            "buyer_fee_minor": amount * 3 // 100,
            "shipping_minor": 0,
            "tax_minor": 0,
            "payable_minor": amount + amount * 3 // 100,
            "schedule_id": "usd-v2",
            "source": "sample",
            "source_verified": False,
            "sample": True,
            "minor_unit_exponent": 2,
            "rounding": "half_up",
            "created_at": now.isoformat(),
            "reviewed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
        r = await c.post(
            f"/v1/auctions/{id}/bids",
            headers={"Authorization": "Bearer " + str(buyer), "Idempotency-Key": "bid"},
            json={"expected_revision": 1, "amount_minor": amount, "fee_quote_id": q},
        )
        assert r.status_code == 200 and r.json()["status"] == "succeeded", r.text

    module = next(
        m
        for m in discover(Path(os.environ["BT_MODULES_PATH"]))
        if m.id == "L13.closing"
    )
    yield app, c, open_lot, bid, module, buyer, watch, listing
    await c.aclose()
    await app.state.pool.close()
    await dependencies.close()


async def clock_at(monkeypatch, module, when):
    async def clock(tx):
        return when

    monkeypatch.setattr(kernel, "server_now", clock)
    fn = module.load("service.py:close")
    monkeypatch.setitem(fn.__globals__, "server_now", clock)
    return fn


@pytest.mark.parametrize("case", ["no_bids", "reserve_not_met", "winner"])
async def test_close_once_at_exact_end_and_replay(auction, monkeypatch, case):
    app, c, open_lot, bid, module, buyer, *_ = auction
    id = await open_lot(600000 if case == "reserve_not_met" else None)
    if case != "no_bids":
        await bid(id)
    lot = await app.state.pool.fetchrow("SELECT * FROM auction_lots WHERE id=$1", id)
    close = await clock_at(monkeypatch, module, lot["ends_at"])
    results = await asyncio.gather(
        *(close(app, id, lot["end_version"], "test-close") for _ in range(3))
    )
    assert results[0] == results[1] == results[2]
    assert results[0]["status"] == (
        "allocation_pending" if case == "winner" else "no_sale"
    )
    assert results[0]["reason"] == (None if case == "winner" else case)
    assert results[0]["currency"] == "USD"
    from bt_contracts.auction.closing import CloseResult

    CloseResult.model_validate(results[0])
    assert await app.state.pool.fetchval("SELECT count(*) FROM l13_auction_closes") == 1
    assert (
        await app.state.pool.fetchval(
            "SELECT close_version FROM auction_lots WHERE id=$1", id
        )
        == 1
    )
    public = (await c.get(f"/v1/auctions/{id}/result")).text
    assert (
        str(buyer) not in public
        and "reserve_minor" not in public
        and "maxima" not in public
    )


async def test_before_end_and_stale_close_job_do_not_close(auction, monkeypatch):
    app, c, open_lot, bid, module, *_ = auction
    id = await open_lot()
    await bid(id)
    lot = await app.state.pool.fetchrow("SELECT * FROM auction_lots WHERE id=$1", id)
    close = await clock_at(
        monkeypatch, module, lot["ends_at"] - timedelta(microseconds=1)
    )
    with pytest.raises(PublicError, match="auction_not_ended"):
        await close(app, id, lot["end_version"], "before")
    with pytest.raises(PublicError, match="stale_end_version"):
        await close(app, id, lot["end_version"] + 1, "stale")
    assert await app.state.pool.fetchval("SELECT count(*) FROM l13_auction_closes") == 0


async def test_lost_orders_response_keeps_original_winner_and_payload(
    auction, monkeypatch
):
    app, c, open_lot, bid, module, buyer, watch, listing = auction
    id = await open_lot()
    await bid(id)
    lot = await app.state.pool.fetchrow("SELECT * FROM auction_lots WHERE id=$1", id)
    close = await clock_at(monkeypatch, module, lot["ends_at"])
    await close(app, id, lot["end_version"], "close")
    order_id = str(uuid4())
    quote_id = str(uuid4())
    calls = []

    class Source:
        async def json(self, name, method, path, **kwargs):
            if name == "pricing":
                assert path == "/internal/v2/auction-quotes"
                assert kwargs["json"]["expected_revision"] == lot["revision"] + 1
                return {
                    "status": "succeeded",
                    "quote": {
                        "id": quote_id,
                        "revision": 1,
                        "buyer_id": str(buyer),
                        "owner_id": str(buyer),
                        "listing_id": str(listing),
                        "listing_revision": 1,
                        "watch_id": str(watch),
                        "price_minor": 500000,
                        "currency": "USD",
                        "auction_id": str(id),
                        "source": "auction",
                        "source_verified": True,
                        "kind": "winner",
                        "payable_minor": 515000,
                    },
                }
            if method == "GET":
                return {
                    "watch_id": str(watch),
                    "listing_id": str(listing),
                    "source_id": str(id),
                    "status": "fenced",
                    "auction_committed": True,
                    "listing_revision": 1,
                    "revision": 2,
                }
            calls.append(kwargs["json"])
            if len(calls) == 1:
                raise PublicError(
                    "unavailable", "Lost response after durable allocation", status=503
                )
            return {
                "status": "succeeded",
                "order": {
                    "id": order_id,
                    "buyer_id": str(buyer),
                    "watch_id": str(watch),
                    "listing_id": str(listing),
                    "quote_id": quote_id,
                    "currency": "USD",
                    "total_minor": 515000,
                },
            }

    reconcile = module.load("reconcile.py:reconcile")
    await reconcile(app, Source(), id)
    assert (
        await app.state.pool.fetchval("SELECT state FROM l13_auction_closes")
        == "allocation_pending"
    )
    assert (
        await app.state.pool.fetchval("SELECT mode FROM auction_lots")
        == "closed_winner"
    )
    await reconcile(app, Source(), id)
    assert calls[0] == calls[1]
    assert await app.state.pool.fetchval(
        "SELECT order_id FROM l13_auction_closes"
    ) == UUID(order_id)
    assert (
        await app.state.pool.fetchval(
            "SELECT count(*) FROM outbox WHERE envelope->>'type'='auction.closed.v1'"
        )
        == 1
    )
