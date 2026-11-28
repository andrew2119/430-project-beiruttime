import json
import io
from datetime import timedelta
from PIL import Image
from uuid import UUID, uuid4
from types import SimpleNamespace
import httpx
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.app.db import create_pool


@pytest_asyncio.fixture
async def catalog(database_url, monkeypatch):
    key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    monkeypatch.setenv("BT_SERVICE_AUTH_PRIVATE_KEY", key)
    seller, other, listing, watch = [uuid4() for _ in range(4)]
    app = create_app(Settings(database_url=database_url, service_name="catalog"))
    app.state.pool = await create_pool(database_url)
    revision = 1
    quotes = {}
    state = SimpleNamespace(
        outage=False, denied=False, lost=False, committed=False, calls=[]
    )

    def upstream(request):
        if request.url.host == "identity":
            actor = request.headers.get("Authorization", "").removeprefix("Bearer ")
            return httpx.Response(
                200,
                json={
                    "actor": {"subject_id": actor, "session_id": "synthetic"},
                    "roles": ["private_seller"],
                    "permissions": ["identity.listings.publish"],
                    "organizations": [],
                    "organization_grants": [],
                },
            )
        if request.url.host == "pricing":
            return httpx.Response(200, json=quotes[request.url.path.split("/")[-1]])
        if request.url.path == "/internal/v1/watches/register":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "status": "succeeded",
                    "resource_id": body["watch_id"],
                    "watch": {
                        "watch_id": body["watch_id"],
                        "listing_id": body["listing_id"],
                        "sale_mode": body["sale_mode"],
                        "status": "available",
                        "revision": 1,
                        "is_demo": False,
                    },
                },
            )
        if state.outage:
            return httpx.Response(503)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "watch_id": str(watch),
                    "listing_id": str(listing),
                    "listing_revision": revision,
                    "revision": 1,
                },
            )
        body = json.loads(request.content)
        state.calls.append(body)
        if state.denied:
            return httpx.Response(
                200, json={"status": "denied", "code": "watch_committed"}
            )
        state.committed = True
        if state.lost:
            state.lost = False
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "watch": {
                    "watch_id": str(watch),
                    "listing_id": str(listing),
                    "status": "withdrawn",
                    "source_id": body["source_id"],
                },
            },
        )

    app.state.catalog_clients = {
        n: DependencyClient(n, "http://" + n, transport=httpx.MockTransport(upstream))
        for n in (
            "identity",
            "orders",
            "pricing",
            "catalog",
            "communications",
            "trust",
            "auction",
        )
    }
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://catalog"
    )
    auth = {"Authorization": "Bearer " + str(seller)}
    created = await c.post(
        "/v1/seller/listings",
        headers={**auth, "Idempotency-Key": "create-fixture"},
        json={
            "facts": {
                "brand": "Synthetic",
                "model": "Sample watch",
                "reference": "Sample",
                "year": 2020,
                "condition": "Synthetic test condition",
                "component_wear": {"case": "Illustrative condition"},
                "location": "Beirut",
                "included": [],
                "no_documents": True,
                "modified": False,
                "modifications": [],
                "ownership_confirmed": True,
                "sale_mode": "fixed_price",
                "currency": "USD",
                "price_minor": 500000,
            }
        },
    )
    assert created.status_code == 201, created.text
    listing = UUID(created.json()["id"])
    watch = UUID(created.json()["physical_watch_id"])
    image = io.BytesIO()
    Image.new("RGB", (80, 80), "gray").save(image, format="JPEG")
    uploaded = await c.post(
        f"/v1/seller/listings/{listing}/media",
        headers={
            **auth,
            "Idempotency-Key": "photo-fixture",
            "If-Match": str(created.json()["revision"]),
            "X-Media-Kind": "public_photo",
            "X-Public-Safe": "true",
            "Content-Type": "application/octet-stream",
        },
        content=image.getvalue(),
    )
    assert uploaded.status_code == 201, uploaded.text
    current = uploaded.json()["listing"]
    # This deterministic transport's clock follows the isolated Catalog DB,
    # rather than relying on sub-millisecond host/VM clock synchronization.
    now = await app.state.pool.fetchval("SELECT clock_timestamp()")
    quote_id = str(uuid4())
    quotes[quote_id] = {
        "id": quote_id,
        "owner_id": str(seller),
        "revision": 1,
        "subject_id": str(listing),
        "subject_revision": current["revision"],
        "purpose": "purchase",
        "source": "sample",
        "source_verified": False,
        "schedule_id": "usd-v2",
        "currency": "USD",
        "price_minor": 500000,
        "minor_unit_exponent": 2,
        "buyer_fee_minor": 15000,
        "seller_commission_minor": 25000,
        "seller_net_minor": 475000,
        "shipping_minor": 0,
        "tax_minor": 0,
        "payable_minor": 515000,
        "sample": True,
        "rounding": "half_up",
        "fx": None,
        "commission_basis": "price_excluding_buyer_fee_shipping_tax",
        "policy": {
            "revision": 2,
            "buyer_fee_bps": 300,
            "seller_commission_bps": 500,
            "shipping": "sample_zero",
            "tax": "sample_zero",
            "fx": "not_applied",
            "currency_exponents": {"USD": 2, "LBP": 2},
        },
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
    }
    published = await c.post(
        f"/v1/seller/listings/{listing}/publish",
        headers={
            **auth,
            "Idempotency-Key": "publish-fixture",
            "If-Match": str(current["revision"]),
        },
        json={"fee_quote_id": quote_id, "rules_version": "usd-v2"},
    )
    assert published.status_code == 200, published.text
    revision = published.json()["revision"]
    headers = {**auth, "Idempotency-Key": "withdraw", "If-Match": str(revision)}
    yield app, c, state, headers, listing, watch, other
    await c.aclose()
    await app.state.pool.close()
    for client in app.state.catalog_clients.values():
        await client.aclose()


async def withdraw(c, headers, id, reason="Unavailable watch"):
    return await c.post(
        f"/v1/listings/{id}/withdrawals", headers=headers, json={"reason": reason}
    )


async def test_pending_before_http_lost_result_replays_same_payload(catalog):
    app, c, state, headers, listing, *_ = catalog
    state.lost = True
    first = await withdraw(c, headers, listing)
    assert first.status_code == 200 and first.json()["status"] == "pending", first.text
    assert state.committed
    assert (
        await app.state.pool.fetchval(
            "SELECT status FROM catalog_listings WHERE id=$1", listing
        )
        == "withdrawal_pending"
    )
    # Public projection is unavailable throughout uncertainty, without deleting private history.
    assert (await c.get(f"/v1/listings/{listing}/publication")).status_code == 404
    second = await withdraw(c, headers, listing)
    assert second.json()["status"] == "succeeded", second.text
    assert state.calls[0] == state.calls[1]
    third = await withdraw(c, headers, listing)
    assert third.json() == second.json()
    assert await app.state.pool.fetchval("SELECT count(*) FROM catalog_listings") == 1
    assert (
        await app.state.pool.fetchval("SELECT count(*) FROM l13_withdrawal_audit") == 2
    )
    assert (
        await app.state.pool.fetchval(
            "SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.listing.withdrawn.v1'"
        )
        == 1
    )


async def test_commitment_denial_returns_exception_preserves_history(catalog):
    app, c, state, headers, listing, *_ = catalog
    state.denied = True
    response = await withdraw(c, headers, listing)
    assert response.json()["status"] == "denied", response.text
    assert response.json()["outcome"]["exception_route"] == "/checkout"
    assert (
        await app.state.pool.fetchval("SELECT status FROM catalog_listings")
        == "published"
    )
    assert (
        await app.state.pool.fetchval("SELECT count(*) FROM l13_withdrawal_audit") == 2
    )


async def test_wrong_seller_stale_revision_and_wrong_retry_do_not_withdraw(catalog):
    app, c, state, headers, listing, watch, other = catalog
    assert (
        await withdraw(c, {**headers, "Authorization": "Bearer " + str(other)}, listing)
    ).status_code == 403
    assert (
        await withdraw(
            c, {**headers, "If-Match": str(int(headers["If-Match"]) + 1)}, listing
        )
    ).status_code == 409
    state.outage = True
    assert (await withdraw(c, headers, listing)).json()["status"] == "pending"
    assert (await withdraw(c, headers, listing, "Changed reason")).status_code == 409
    assert not state.calls
    assert (
        await app.state.pool.fetchval("SELECT status FROM catalog_listings")
        == "withdrawal_pending"
    )
    second = await c.post(
        "/v1/seller/listings",
        headers={**headers, "Idempotency-Key": "another-draft"},
        json={},
    )
    assert second.status_code == 201, second.text
    conflict = await withdraw(
        c, {**headers, "If-Match": str(second.json()["revision"])}, second.json()["id"]
    )
    assert (
        conflict.status_code == 409
        and conflict.json()["error"]["code"] == "idempotency_conflict"
    ), conflict.text
    assert (
        await app.state.pool.fetchval("SELECT count(*) FROM l13_listing_withdrawals")
        == 1
    )


async def test_pending_published_edit_blocks_withdrawal_before_any_remote_mutation(
    catalog,
):
    app, c, state, headers, listing, *_ = catalog
    current = await c.get(f"/v1/seller/listings/{listing}", headers=headers)
    facts = current.json()["facts"]
    state.outage = True
    editing = await c.post(
        f"/v1/seller/listings/{listing}/revisions",
        headers={**headers, "Idempotency-Key": "pending-edit"},
        json={
            "facts": {**facts, "price_minor": facts["price_minor"] + 100},
            "reason": "Synthetic current revision edit",
        },
    )
    assert editing.status_code == 503, editing.text
    history = await c.get(f"/v1/seller/listings/{listing}/revisions", headers=headers)
    assert history.json()["pending_operation_id"] is not None
    before_calls = list(state.calls)
    denied = await withdraw(c, headers, listing)
    assert (
        denied.status_code == 409 and denied.json()["error"]["code"] == "edit_pending"
    ), denied.text
    assert state.calls == before_calls
    assert (
        await app.state.pool.fetchval("SELECT count(*) FROM l13_listing_withdrawals")
        == 0
    )
    row = await app.state.pool.fetchrow(
        "SELECT status,revision FROM catalog_listings WHERE id=$1", listing
    )
    assert (
        row["status"] == "published" and row["revision"] == current.json()["revision"]
    )
