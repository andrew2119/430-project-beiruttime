"""Pricing v3 protocol fixtures. No database or connected service is started."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from bt_bulkheads import DependencyClient
from bt_contracts_core.errors import PublicError


def source():
    now = datetime.now(timezone.utc)
    order = {"id": uuid4(), "buyer_id": uuid4(), "quote_id": uuid4(), "listing_id": uuid4(), "currency": "USD",
             "total_minor": 515000, "revision": 1, "state": "awaiting_notification"}
    snapshot = {"id": str(order["quote_id"]), "owner_id": str(order["buyer_id"]), "currency": "USD",
                "payable_minor": 515000, "revision": 2, "reviewed_at": (now - timedelta(minutes=1)).isoformat(),
                "expires_at": (now + timedelta(minutes=14)).isoformat()}
    return order, snapshot, now


@pytest.fixture
def commitment_module(lane_modules):
    return lane_modules("service_app.quote_commitments", "services/orders/runtime/service_app/quote_commitments.py")


def test_original_allocation_time_and_exact_fields_are_retained(commitment_module):
    order, snapshot, now = source()
    body = commitment_module.attestation(order, snapshot, now)
    assert set(body) == {"buyer_id", "order_id", "quote_revision", "total_minor", "committed_at"}
    assert body["order_id"] == str(order["id"])
    assert body["total_minor"] == 515000
    assert datetime.fromisoformat(body["committed_at"]) == now


@pytest.mark.parametrize("field,value", [("currency", "LBP"), ("owner_id", str(uuid4())),
    ("id", str(uuid4())), ("payable_minor", 515001), ("revision", True), ("reviewed_at", "invalid")])
def test_changed_binding_cannot_create_an_attestation(commitment_module, field, value):
    order, snapshot, now = source()
    with pytest.raises(PublicError, match="quote_commitment_mismatch"):
        commitment_module.attestation(order, snapshot | {field: value}, now)


@pytest.mark.parametrize("boundary", ["before_review", "at_expiry", "after_expiry", "naive"])
def test_only_real_admission_time_can_be_attested(commitment_module, boundary):
    order, snapshot, now = source()
    when = {"before_review": now - timedelta(minutes=2), "at_expiry": now + timedelta(minutes=14),
            "after_expiry": now + timedelta(minutes=15), "naive": now.replace(tzinfo=None)}[boundary]
    with pytest.raises(PublicError, match="quote_commitment_mismatch"):
        commitment_module.attestation(order, snapshot, when)


@pytest.mark.asyncio
async def test_same_order_retry_cannot_replace_accepted_time(commitment_module):
    order, snapshot, now = source()
    original = commitment_module.attestation(order, snapshot, now)
    tx = SimpleNamespace(fetchval=AsyncMock(return_value=None), fetchrow=AsyncMock(return_value={
        "quote_id": order["quote_id"], "payload": json.dumps(original)}))
    await commitment_module.retain_commitment(tx, order, snapshot, now)
    with pytest.raises(PublicError, match="quote_commitment_conflict"):
        await commitment_module.retain_commitment(tx, order, snapshot, now + timedelta(seconds=1))


@pytest.mark.parametrize("status,state", [(200, "acknowledged"), (201, "acknowledged"),
    (202, "pending"), (400, "reconciliation"), (409, "reconciliation"), (410, "reconciliation"),
    (422, "reconciliation"), (401, "pending"), (403, "pending"), (404, "pending"),
    (429, "pending"), (503, "pending"), (None, "pending")])
def test_unknown_or_unavailable_is_never_acknowledged(commitment_module, status, state):
    assert commitment_module.result_state(status)[0] == state


def committed_proof(order, **changes):
    return {"quote_id": str(order["quote_id"]), "quote_revision": 2, "buyer_id": str(order["buyer_id"]),
            "source_id": str(order["listing_id"]), "source_revision": 1, "kind": "purchase",
            "currency": "USD", "total_minor": order["total_minor"], "expires_at": None,
            "schedule_id": "usd-v2", "policy_revision": 2, "rounding": "half_up", "status": "valid",
            "economics": "committed", "execution_authority": "not_granted", **changes}


@pytest.fixture
def relay_fixture(commitment_module, monkeypatch):
    order, snapshot, now = source()
    intent = {"order_id": order["id"], "quote_id": order["quote_id"],
              "payload": json.dumps(commitment_module.attestation(order, snapshot, now)),
              "state": "pending", "lease": None, "attempts": 0}
    state = {"active": 0, "due": True, "audits": [], "events": [], "locks": []}

    async def fetch(sql, lease):
        assert sql.lstrip().startswith("UPDATE l13_quote_commitments")
        assert "LIMIT 5 FOR UPDATE SKIP LOCKED" in sql
        if intent["state"] != "pending" or not state["due"]:
            return []
        intent.update(lease=lease, attempts=intent["attempts"] + 1)
        return [dict(intent)]

    async def fetchrow(sql, *args):
        assert "SELECT * FROM l08_orders" in sql and "FOR UPDATE" in sql
        state["locks"].append("order")
        return order

    async def fetchval(sql, order_id, *args):
        if sql.startswith("SELECT listing_revision FROM l13_order_quotes"):
            return 1
        lease, outcome, code = args
        assert sql.lstrip().startswith("UPDATE l13_quote_commitments")
        assert state["locks"][-1] == "order"
        state["locks"].append("intent")
        if intent["state"] != "pending" or intent["lease"] != lease:
            return None
        intent.update(state=outcome, lease=None, last_error=code)
        state["due"] = False
        return 1

    async def execute(sql, *args):
        if sql.startswith("INSERT INTO l08_audit"):
            state["audits"].append(args)
        elif "INSERT INTO outbox" in sql:
            state["events"].append(json.loads(args[2]))
        else:
            raise AssertionError(sql)

    tx = SimpleNamespace(fetch=fetch, fetchrow=fetchrow, fetchval=fetchval, execute=execute)
    pool = object()

    @asynccontextmanager
    async def unit_of_work(expected):
        assert expected is pool
        state["active"] += 1
        try:
            yield tx
        finally:
            state["active"] -= 1

    monkeypatch.setattr(commitment_module, "unit_of_work", unit_of_work)
    monkeypatch.setattr(commitment_module, "delivery_headers", lambda destination: {"Authorization": "Bearer synthetic"})
    return commitment_module, pool, order, intent, state, now


@pytest.mark.asyncio
async def test_lost_response_retries_original_payload_outside_locks_even_after_expiry(relay_fixture):
    module, pool, order, intent, state, _ = relay_fixture
    requests = []
    statuses = [503, 200]

    async def upstream(request):
        assert state["active"] == 0
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=committed_proof(order))
        return httpx.Response(statuses.pop(0))

    pricing = DependencyClient("pricing", "http://pricing", transport=httpx.MockTransport(upstream))
    try:
        assert await module.relay_commitments(pool, pricing) == 1
        assert intent["state"] == "pending" and not state["events"]
        # The next admitted retry uses the original allocation, never the clock now.
        order["state"] = "expired_released"
        state["due"] = True
        assert await module.relay_commitments(pool, pricing) == 1
        assert intent["state"] == "acknowledged"
        assert order["state"] == "expired_released"  # No revival, payment or stock mutation.
        posts = [request for request in requests if request.method == "POST"]
        assert posts[0].content == posts[1].content
        assert posts[0].headers["Idempotency-Key"] == posts[1].headers["Idempotency-Key"]
        assert json.loads(posts[1].content) == json.loads(intent["payload"])
        assert posts[1].url.path == f"/internal/v3/quotes/{order['quote_id']}/commit"
        assert await module.relay_commitments(pool, pricing) == 0
        assert len(posts) == len(state["audits"]) + 1 == 2
        assert len(requests) == 3
        assert len(state["events"]) == 1
    finally:
        await pricing.aclose()


@pytest.mark.asyncio
async def test_known_refusal_retains_original_commitment_for_support(relay_fixture):
    module, pool, order, intent, state, _ = relay_fixture
    original = intent["payload"]
    pricing = DependencyClient("pricing", "http://pricing", transport=httpx.MockTransport(lambda request: httpx.Response(409)))
    try:
        await module.relay_commitments(pool, pricing)
        assert intent["state"] == "reconciliation" and intent["payload"] == original
        assert order["state"] == "awaiting_notification"
        assert len(state["events"]) == 1
        assert state["events"][0]["data"]["outcome"] == "reconciliation"
        assert state["events"][0]["data"]["next_action"] == "operator_reconciliation"
        assert await module.relay_commitments(pool, pricing) == 0
    finally:
        await pricing.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [("denied", "reconciliation"), ("pending", "pending"),
    ("unavailable", "pending"), ("unknown", "pending"), (["succeeded"], "pending")])
async def test_http_success_is_not_a_domain_success(relay_fixture, status, expected):
    module, pool, _, intent, state, _ = relay_fixture
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.method == "POST"
        return httpx.Response(200, json={"status": status})

    pricing = DependencyClient("pricing", "http://pricing", transport=httpx.MockTransport(upstream))
    try:
        await module.relay_commitments(pool, pricing)
        assert intent["state"] == expected and len(calls) == 1
    finally:
        await pricing.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,expected", [
    ({"buyer_id": str(uuid4())}, "reconciliation"), ({"quote_id": str(uuid4())}, "reconciliation"),
    ({"quote_revision": 3}, "reconciliation"), ({"total_minor": 515001}, "reconciliation"),
    ({"source_id": str(uuid4())}, "reconciliation"), ({"source_revision": 2}, "reconciliation"),
    ({"economics": "preview", "expires_at": "2027-01-01T00:00:00Z"}, "pending"),
    ({"execution_authority": "granted"}, "pending"),
])
async def test_readback_must_prove_exact_committed_snapshot(relay_fixture, changes, expected):
    module, pool, order, intent, state, _ = relay_fixture

    def upstream(request):
        assert state["active"] == 0
        return httpx.Response(200, json={"status": "succeeded"} if request.method == "POST"
                              else committed_proof(order, **changes))

    pricing = DependencyClient("pricing", "http://pricing", transport=httpx.MockTransport(upstream))
    try:
        await module.relay_commitments(pool, pricing)
        assert intent["state"] == expected
        assert order["state"] == "awaiting_notification"
    finally:
        await pricing.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"order_id": str(uuid4())}, {"total_minor": True}, {"unknown": "field"}])
async def test_corrupt_local_binding_is_held_before_network(relay_fixture, change):
    module, pool, _, intent, _, _ = relay_fixture
    intent["payload"] = json.dumps(json.loads(intent["payload"]) | change)
    pricing = SimpleNamespace(request=AsyncMock())
    await module.relay_commitments(pool, pricing)
    pricing.request.assert_not_awaited()
    assert intent["state"] == "reconciliation"


@pytest.mark.asyncio
async def test_missing_service_credentials_remain_pending(relay_fixture, monkeypatch):
    module, pool, _, intent, state, _ = relay_fixture

    def missing(_):
        raise RuntimeError("Service credentials unavailable")

    monkeypatch.setattr(module, "delivery_headers", missing)
    pricing = SimpleNamespace(request=AsyncMock())
    await module.relay_commitments(pool, pricing)
    pricing.request.assert_not_awaited()
    assert intent["state"] == "pending" and not state["events"]
