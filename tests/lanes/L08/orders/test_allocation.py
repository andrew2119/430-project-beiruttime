import asyncio
import importlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID
import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.app import db


@pytest_asyncio.fixture
async def market(database_url):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    app = create_app(Settings(database_url=database_url, service_name="orders", service_auth_public_key=public))
    app.state.pool = await db.create_pool(database_url)
    users = {}
    quotes = {}
    outage = {"identity": False, "pricing": False}

    def upstream(request):
        name = request.url.host
        if outage.get(name):
            return httpx.Response(503)
        if name == "pricing" and outage.get("pricing_auth"):
            return httpx.Response(401)
        if name == "identity":
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            if token not in users:
                return httpx.Response(401)
            return httpx.Response(200, json=users[token])
        quote_id = request.url.path.split("/")[4]
        return httpx.Response(200, json=quotes[quote_id]) if quote_id in quotes else httpx.Response(404)

    app.state.allocation_clients = {
        name: DependencyClient(name, "http://" + name, transport=httpx.MockTransport(upstream))
        for name in ("identity", "pricing", "catalog", "communications")
    }
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://orders")

    def user(roles=None, permissions=None, org=None, grants=None):
        identity = uuid4()
        token = str(identity)
        users[token] = {
            "actor": {"subject_id": str(identity), "session_id": "test", "organization_id": str(org) if org else None},
            "roles": roles or ["buyer"],
            "permissions": permissions or [],
            "organizations": [str(org)] if org else [],
            "organization_grants": grants or [],
        }
        return identity, {"Authorization": "Bearer " + token}

    def service(name):
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": name,
                "iss": "beirut-time-identity",
                "aud": "orders",
                "type": "service",
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            private,
            algorithm="RS256",
        )
        return {"Authorization": "Bearer " + token}

    async def watch(sale_mode="fixed", org=None, is_demo=False, seller_id=None):
        value = {
            "watch_id": str(uuid4()),
            "listing_id": str(uuid4()),
            "seller_id": str(seller_id or uuid4()),
            "organization_id": str(org) if org else None,
            "listing_revision": 1,
            "sale_mode": sale_mode,
            "is_demo": is_demo,
        }
        result = await client.post(
            "/internal/v1/watches/register", json=value, headers={**service("catalog"), "Idempotency-Key": str(uuid4())}
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "succeeded", result.text
        return value

    def quote(watch, buyer, **changes):
        quote_id = str(uuid4())
        quotes[quote_id] = {
            "quote_id": quote_id,
            "buyer_id": str(buyer),
            "listing_id": watch["listing_id"],
            "listing_revision": 1,
            "currency": "USD",
            "total_minor": 125000,
            "status": "valid",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            **changes,
        }
        return quote_id

    yield app, client, user, service, watch, quote, users, quotes, outage
    await client.aclose()
    for dependency in app.state.allocation_clients.values():
        await dependency.aclose()
    await app.state.pool.close()


async def reserve(client, watch, quote, headers, key=None, revision=1):
    return await client.post(
        "/v1/reservations",
        json={"watch_id": watch["watch_id"], "quote_id": quote, "expected_revision": revision},
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
    )


@pytest.mark.asyncio
async def test_racing_buyers_exclusive_persistent_outcome(market):
    app, c, user, svc, new_watch, quote, *_ = market
    watch = await new_watch()
    a, ha = user()
    b, hb = user()
    qa = quote(watch, a)
    qb = quote(watch, b)
    results = await asyncio.gather(reserve(c, watch, qa, ha, "buyer-a"), reserve(c, watch, qb, hb, "buyer-b"))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert sorted(r.json()["status"] for r in results) == ["denied", "succeeded"]
    winner = next(r.json() for r in results if r.json()["status"] == "succeeded")
    loser = next(r.json() for r in results if r.json()["status"] == "denied")
    assert loser["code"] == "watch_unavailable" and loser["payment_authority"] is False
    assert winner["order"]["state"] == "awaiting_payment" and not winner["order"]["payment_authority"]
    assert winner["order"]["quote_id"] == (qa if winner["order"]["buyer_id"] == str(a) else qb)
    winning_headers = ha if winner["order"]["buyer_id"] == str(a) else hb
    detail = (await c.get('/v1/orders/' + winner['resource_id'], headers=winning_headers)).json()
    assert detail['order']['quote_id'] == winner['order']['quote_id']
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 1
    token = ha if winner["order"]["buyer_id"] == str(a) else hb
    repeated = await reserve(c, watch, qa if token == ha else qb, token, "buyer-a" if token == ha else "buyer-b")
    assert repeated.json() == winner
    assert (await c.get("/v1/operations/" + winner["id"], headers=token)).json() == winner
    assert (await c.get("/v1/operations/" + winner["id"], headers=hb if token == ha else ha)).status_code == 404
    assert (
        await app.state.pool.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='orders.reserved.v1'") == 2
    )
    notices = await app.state.pool.fetch(
        "SELECT envelope,destination FROM outbox WHERE envelope->>'type'='orders.reservation-created.v1'"
    )
    assert len(notices) == 1 and notices[0]["destination"] == "communications"
    notice = json.loads(notices[0]["envelope"])
    assert notice["data"] == {
        "occurrence_id": "reservation:" + winner["order"]["id"],
        "recipient_id": winner["order"]["buyer_id"],
        "kind": "reservation_ready",
        "resource_id": winner["order"]["id"],
        "resource_revision": 1,
        "resource_owner_id": winner["order"]["buyer_id"],
        "event_time": notice["data"]["event_time"],
        "required": True,
        "sample": False,
    }
    assert datetime.fromisoformat(notice["data"]["event_time"]) == datetime.fromisoformat(notice["time"])
    # Recreate an app/pool: the database, not process memory, is authoritative.
    second = create_app(app.state.settings)
    second.state.pool = await db.create_pool(app.state.settings.database_url)
    second.state.allocation_clients = app.state.allocation_clients
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url="http://orders") as restored:
            assert (await restored.get("/v1/orders/" + winner["resource_id"], headers=token)).json()["order"] == winner[
                "order"
            ]
    finally:
        await second.state.pool.close()


@pytest.mark.asyncio
async def test_idempotency_stale_self_and_quote_binding(market):
    app, c, user, svc, new_watch, quote, users, quotes, outage = market
    watch = await new_watch()
    buyer, headers = user()
    q = quote(watch, buyer)
    assert (await reserve(c, watch, q, headers, "stale", 2)).json()["code"] == "stale_revision"
    other, ho = user()
    assert (await reserve(c, watch, q, ho)).json()["code"] == "quote_mismatch"
    own_header = {"Authorization": "Bearer " + watch["seller_id"]}
    users[watch["seller_id"]] = {"actor": {"subject_id": watch["seller_id"], "session_id": "s"}, "roles": ["buyer"]}
    assert (await reserve(c, watch, quote(watch, UUID(watch["seller_id"])), own_header)).json()[
        "code"
    ] == "self_purchase"
    good = await reserve(c, watch, q, headers, "same")
    assert good.json()["status"] == "succeeded"
    assert (await reserve(c, watch, quote(watch, buyer), headers, "same")).status_code == 409
    assert (await c.get("/v1/orders/" + good.json()["resource_id"], headers=ho)).status_code == 403
    assert (await c.get("/v1/orders", headers=ho)).json()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-1, 0])
async def test_expired_equal_quotes_never_allocate(market, offset):
    app, c, user, svc, new_watch, quote, *_ = market
    watch = await new_watch()
    buyer, headers = user()
    q = quote(watch, buyer, expires_at=(datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat())
    assert (await reserve(c, watch, q, headers)).json()["code"] == "quote_expired"
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 0


@pytest.mark.asyncio
async def test_outage_malformed_no_success_and_retry(market):
    app, c, user, svc, new_watch, quote, users, quotes, outage = market
    watch = await new_watch()
    buyer, headers = user()
    q = quote(watch, buyer)
    outage["identity"] = True
    assert (await reserve(c, watch, q, headers, "retry")).status_code == 503
    outage["identity"] = False
    outage["pricing"] = True
    assert (await reserve(c, watch, q, headers, "retry")).status_code == 503
    outage["pricing"] = False
    quotes[q]["total_minor"] = 1.5
    assert (await reserve(c, watch, q, headers, "retry")).status_code == 503
    quotes[q]["total_minor"] = 125000
    assert (await reserve(c, watch, q, headers, "retry")).json()["status"] == "succeeded"


@pytest.mark.asyncio
async def test_auction_fences_deny_fixed_and_competing_sources(market):
    app, c, user, svc, new_watch, quote, *_ = market
    fixed = await new_watch()
    auction = await new_watch("auction")
    buyer, headers = user()
    body = {"source_id": str(uuid4()), "expected_revision": 1, "reason": "Auction opens"}

    async def fence(watch, key, changes=None):
        return await c.post(
            "/internal/v1/watches/" + watch["watch_id"] + "/fences",
            json={**body, **(changes or {})},
            headers={**svc("auction"), "Idempotency-Key": key},
        )

    assert (await fence(fixed, "fixed")).json()["code"] == "sale_mode_unavailable"
    assert (await reserve(c, auction, quote(auction, buyer), headers)).json()["code"] == "sale_mode_unavailable"
    assert (await fence(auction, "first")).json()["status"] == "succeeded"
    assert (await fence(auction, "again")).json()["status"] == "succeeded"
    assert (await fence(auction, "other", {"source_id": str(uuid4())})).json()["code"] == "watch_unavailable"
    denied = await c.post(
        "/internal/v1/watches/register", json=fixed, headers={**headers, "Idempotency-Key": "user-cannot-register"}
    )
    assert denied.status_code == 401
    projection = (await c.get("/v1/watches/" + fixed["watch_id"] + "/availability")).json()
    assert projection.keys() == {"watch_id", "listing_id", "sale_mode", "status", "revision", "is_demo"}
    assert (await c.get("/v1/listings/" + fixed["listing_id"] + "/availability")).json() == projection
    current = await c.get(
        "/internal/v1/watches/" + auction["watch_id"] + "/fence",
        params={"source_id": body["source_id"]},
        headers=svc("auction"),
    )
    assert current.json()["source_matches"] is True
    assert (
        await c.get(
            "/internal/v1/watches/" + auction["watch_id"] + "/fence",
            params={"source_id": str(uuid4())},
            headers=svc("catalog"),
        )
    ).json()["source_matches"] is False
    assert (
        await c.get(
            "/internal/v1/watches/" + auction["watch_id"] + "/fence",
            params={"source_id": body["source_id"]},
            headers=headers,
        )
    ).status_code == 401
    registered = (
        await c.post(
            "/internal/v1/watches/register",
            json=fixed,
            headers={**svc("catalog"), "Idempotency-Key": "repeat-registration"},
        )
    ).json()
    assert (await c.get("/internal/v1/operations/" + registered["id"], headers=svc("catalog"))).json() == registered
    assert (await c.get("/internal/v1/operations/" + registered["id"], headers=svc("auction"))).status_code == 404


@pytest.mark.asyncio
async def test_expiry_retains_fence_and_state_scope(market):
    app, c, user, svc, new_watch, quote, *_ = market
    watch = await new_watch()
    buyer, headers = user()
    q = quote(watch, buyer)
    result = (await reserve(c, watch, q, headers)).json()
    order_id = result["resource_id"]
    _, operator = user(["operator"], ["orders.manage", "orders.intake", "orders.read"])
    path = "/v1/orders/" + order_id + "/transitions"
    for state in ("paid", "released", "completed", "cancelled"):
        value = await c.post(
            path,
            json={"state": state, "expected_revision": 1, "reason": "Unpaid"},
            headers={**operator, "Idempotency-Key": state},
        )
        assert value.json()["code"] == "transition_unreleased"
    assert (
        await c.post(
            path,
            json={"state": "payment_unknown", "expected_revision": 1, "reason": "Check"},
            headers={**headers, "Idempotency-Key": "bad"},
        )
    ).status_code == 403
    await app.state.pool.execute("UPDATE l08_orders SET deadline=clock_timestamp() WHERE id=$1", UUID(order_id))
    module = next(m for m in app.state.modules if m.id == "L08.allocation")
    assert await module.load("workers.py:expire")(app.state.pool) == 1
    assert await module.load("workers.py:expire")(app.state.pool) == 0
    current = (await c.get("/v1/orders/" + order_id, headers=headers)).json()
    assert current["order"]["state"] == "expired_fenced"
    assert (await c.get("/v1/watches/" + watch["watch_id"] + "/availability")).json()["status"] == "reserved"
    b, hb = user()
    assert (await reserve(c, watch, quote(watch, b), hb)).json()["code"] == "watch_unavailable"
    assert any(h["action"] == "expiry-fence" for h in current["history"])


@pytest.mark.asyncio
async def test_custody_pre_release_and_org_scope(market):
    app, c, user, svc, new_watch, quote, *_ = market
    org = uuid4()
    watch = await new_watch(org=org)
    buyer, headers = user()
    order_id = (await reserve(c, watch, quote(watch, buyer), headers)).json()["resource_id"]
    _, wrong = user(["operator"], ["orders.intake"], org=uuid4())
    _, right = user(
        ["brand"], org=org, grants=[{"organization_id": str(org), "permissions": ["orders.intake"], "roles": ["brand"]}]
    )
    fact = {
        "expected_revision": 1,
        "actual_watch": "Sample watch serial S-1",
        "accessories": ["Box"],
        "location": "Intake desk",
        "condition": "Case scratches",
        "occurred_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        "reason": "Received for assessment",
    }
    url = "/v1/orders/" + order_id + "/intake"
    assert (await c.post(url, json=fact, headers={**wrong, "Idempotency-Key": "wrong"})).status_code == 403
    result = await c.post(url, json=fact, headers={**right, "Idempotency-Key": "right"})
    assert result.json()["final_handover"] is False
    assert (await c.post(url, json=fact, headers={**right, "Idempotency-Key": "right"})).json() == result.json()
    assert (await c.post(url, json=fact, headers={**right, "Idempotency-Key": "stale"})).json()[
        "code"
    ] == "stale_revision"
    assert (await c.get(url, headers=headers)).status_code == 403
    assert len((await c.get(url, headers=right)).json()["items"]) == 1
    receipt_url = "/v1/custody/receipts/" + result.json()["resource_id"]
    proof = (await c.get(receipt_url, headers=right)).json()
    assert proof["valid"] is True and proof["organization_id"] == str(org)
    assert proof["id"] == result.json()["resource_id"] and proof["order_id"] == order_id
    assert "condition" not in proof and "actual_watch" not in proof
    assert (await c.get(receipt_url, headers=headers)).status_code == 403
    _, staff = user(['business_staff'], org=org, grants=[{'organization_id':str(org), 'permissions':['business.records.read','business.jobs.write'], 'roles':['business_staff']}])
    assert (await c.get(receipt_url, headers=staff)).json()['valid'] is True
    other_org = uuid4()
    _, unrelated = user(['business_staff'], org=other_org, grants=[{'organization_id':str(other_org), 'permissions':['business.records.read'], 'roles':['business_staff']}])
    assert (await c.get(receipt_url, headers=unrelated)).status_code == 403
    _, unscoped = user(['operator'], ['business.records.read'], org=org)
    assert (await c.get(receipt_url, headers=unscoped)).status_code == 403
    newer = await c.post(url, json={**fact, "expected_revision": 2}, headers={**right, "Idempotency-Key": "next-fact"})
    assert newer.json()["status"] == "succeeded"
    assert (await c.get(receipt_url, headers=right)).status_code == 409
    data = await app.state.pool.fetch("SELECT envelope FROM outbox WHERE envelope->>'type'='orders.intake-recorded.v1'")
    assert all("Case scratches" not in row["envelope"] and "Intake desk" not in row["envelope"] for row in data)


@pytest.mark.asyncio
async def test_replayed_privileged_command_requires_current_permission(market):
    app, c, user, svc, new_watch, quote, users, *_ = market
    watch = await new_watch()
    buyer, headers = user()
    order_id = (await reserve(c, watch, quote(watch, buyer), headers)).json()["resource_id"]
    operator_id, operator = user(["operator"], ["orders.manage", "orders.read"])
    body = {"state": "payment_unknown", "expected_revision": 1, "reason": "Unknown provider result"}
    path = "/v1/orders/" + order_id + "/transitions"
    response = await c.post(path, json=body, headers={**operator, "Idempotency-Key": "hold"})
    assert response.json()["status"] == "succeeded"
    users[str(operator_id)]["permissions"] = []
    assert (await c.post(path, json=body, headers={**operator, "Idempotency-Key": "hold"})).status_code == 403
    assert (await c.get("/v1/orders/" + order_id, headers=operator)).status_code == 403
    await app.state.pool.execute("UPDATE l08_orders SET deadline=clock_timestamp() WHERE id=$1", UUID(order_id))
    module = next(m for m in app.state.modules if m.id == "L08.allocation")
    assert await module.load("workers.py:expire")(app.state.pool) == 0
    assert (await c.get("/v1/orders/" + order_id, headers=headers)).json()["order"]["state"] == "payment_unknown"


@pytest.mark.asyncio
async def test_register_duplicate_listing_and_many_buyers(market):
    app, c, user, svc, new_watch, quote, *_ = market
    watch = await new_watch()
    result = await c.post(
        "/internal/v1/watches/register",
        json={**watch, "watch_id": str(uuid4())},
        headers={**svc("catalog"), "Idempotency-Key": "same-listing"},
    )
    assert result.json()["code"] == "listing_already_registered"
    users = [user() for _ in range(12)]
    results = await asyncio.gather(*(reserve(c, watch, quote(watch, buyer), headers) for buyer, headers in users))
    assert sum(r.status_code == 200 and r.json()["status"] == "succeeded" for r in results) == 1
    assert all(r.status_code == 503 or r.json()["status"] in ("succeeded", "denied") for r in results)
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 1


@pytest.mark.asyncio
async def test_malformed_principal_cannot_authorize_or_leak_inputs(market):
    app, c, user, svc, new_watch, quote, users, *_ = market
    watch = await new_watch()
    buyer, headers = user()
    q = quote(watch, buyer)
    users[str(buyer)] = {"actor": {"subject_id": "invalid"}, "roles": ["buyer"]}
    response = await reserve(c, watch, q, headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "identity_unavailable"
    assert "invalid" not in response.text
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 0


@pytest.mark.asyncio
async def test_buyer_workspace_feed_is_scoped_bounded_and_truthfully_labeled(market):
    app, c, user, svc, new_watch, quote, *_ = market
    buyer, headers = user()
    seller, seller_headers = user()
    ids = []
    for sample in (True, False, True):
        watch = await new_watch(is_demo=sample, seller_id=seller)
        order = (await reserve(c, watch, quote(watch, buyer), headers)).json()["order"]
        assert order["is_demo"] is sample and order["listing_id"] == watch["listing_id"]
        ids.append(order["id"])
    first = (await c.get("/v1/me/reservations?limit=2", headers=headers)).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = (
        await c.get("/v1/me/reservations", params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers)
    ).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    all_items = first["items"] + second["items"]
    assert {row["reservation_id"] for row in all_items} == set(ids)
    assert all(row["buyer_id"] == str(buyer) and row["state"] == "awaiting_payment" for row in all_items)
    assert sum(row["is_demo"] for row in all_items) == 2
    assert (await c.get("/v1/me/reservations", headers=seller_headers)).json() == {"items": [], "next_cursor": None}
    assert len((await c.get("/v1/orders", headers=seller_headers)).json()["items"]) == 3
    assert (await c.get("/v1/me/reservations?limit=101", headers=headers)).status_code == 422
    assert (
        await c.get("/v1/me/reservations", params={"cursor": first["next_cursor"]}, headers=seller_headers)
    ).status_code == 422
    await app.state.pool.execute("UPDATE l08_orders SET deadline=clock_timestamp() WHERE buyer_id=$1", buyer)
    assert (await c.get("/v1/me/reservations", headers=headers)).json()["items"] == []
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_watches WHERE status='reserved'") == 3


@pytest.mark.asyncio
async def test_pricing_auth_expiry_keeps_retry_unconfirmed_until_reauthorized(market):
    app, c, user, svc, new_watch, quote, users, quotes, outage = market
    watch = await new_watch()
    buyer, headers = user()
    current_quote = quote(watch, buyer)
    outage["pricing_auth"] = True
    denied = await reserve(c, watch, current_quote, headers, "same-after-refresh")
    assert denied.status_code == 401
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_orders") == 0
    assert (
        await app.state.pool.fetchval("SELECT count(*) FROM l08_operations WHERE actor_key=$1", "user:" + str(buyer))
        == 0
    )
    outage["pricing_auth"] = False
    assert (await reserve(c, watch, current_quote, headers, "same-after-refresh")).json()["status"] == "succeeded"


@pytest.mark.asyncio
async def test_selected_organization_preserves_authentication_expiry(market):
    app, client, *_ = market
    response = await client.get(
        "/v1/orders", params={"organization_id": str(uuid4())}, headers={"Authorization": "Bearer expired"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_released_communications_receiver_keeps_the_bounded_client(market):
    app, *_ = market
    route = next(route for route in app.routes if getattr(route, "path", "") == "/v1/reservations")
    module = importlib.import_module(route.endpoint.__module__.rsplit(".", 1)[0] + ".communications")
    calls = []

    def receiver(request):
        calls.append(request)
        return httpx.Response(200, json={"accepted": True})

    dependency = DependencyClient("communications", "http://communications", transport=httpx.MockTransport(receiver))
    try:
        adapter = module.InboxDestination(dependency)
        response = await adapter.request(
            "POST", "/internal/v1/events", json={"id": "same-event"}, headers={"Authorization": "Bearer service-test"}
        )
        assert response.json() == {"accepted": True}
        assert calls[0].url.path == "/internal/v1/inbox/events"
        assert calls[0].headers["Authorization"] == "Bearer service-test"
        assert json.loads(calls[0].content) == {"id": "same-event"}
        with pytest.raises(ValueError):
            await adapter.request("POST", "/unregistered-path", json={})
        assert len(calls) == 1
    finally:
        await dependency.aclose()
