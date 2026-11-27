from datetime import datetime, timezone, timedelta
from uuid import uuid4
import httpx
import jwt
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.app import db

pytest_plugins = []


@pytest_asyncio.fixture
async def market(database_url, monkeypatch):
    monkeypatch.setenv(
        "BT_SIMULATED_PAYMENT_SECRET", "synthetic-signing-secret-for-local-proofs-only"
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    monkeypatch.setenv("BT_SERVICE_AUTH_PRIVATE_KEY", private)
    app = create_app(
        Settings(
            database_url=database_url,
            service_name="orders",
            service_auth_public_key=public,
        )
    )
    app.state.pool = await db.create_pool(database_url)
    users = {}
    quotes = {}
    listings = {}
    validations = {}
    app.state.l13_retained_overrides = {}

    def upstream(request):
        if request.url.host == "identity":
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            return (
                httpx.Response(200, json=users[token])
                if token in users
                else httpx.Response(401)
            )
        if request.url.host == "catalog":
            id = request.url.path.split("/")[3]
            return (
                httpx.Response(200, json=listings[id])
                if id in listings
                else httpx.Response(404)
            )
        id = (
            request.url.path.split("/")[-2]
            if request.url.path.endswith(("/validation", "/retained"))
            else request.url.path.split("/")[-1]
        )
        if "/internal/v2/" in request.url.path and request.url.params.get(
            "buyer_id"
        ) != validations.get(id, {}).get("buyer_id"):
            return httpx.Response(403)
        if request.url.path.endswith("/retained"):
            if id not in quotes:
                return httpx.Response(404)
            q, current = quotes[id], validations[id]
            financial = {
                field: q[field]
                for field in (
                    "price_minor",
                    "buyer_fee_minor",
                    "seller_commission_minor",
                    "seller_net_minor",
                    "shipping_minor",
                    "tax_minor",
                    "payable_minor",
                    "currency",
                    "schedule_id",
                    "rounding",
                    "minor_unit_exponent",
                    "sample",
                    "policy",
                    "expires_at",
                    "reviewed_at",
                )
            }
            financial.update(
                {
                    field: current[field]
                    for field in (
                        "quote_id",
                        "quote_revision",
                        "buyer_id",
                        "source_id",
                        "source_revision",
                    )
                }
            )
            if current["kind"] == "offer":
                financial.update(
                    source_id=current["listing_id"],
                    source_revision=current["listing_revision"],
                )
            financial.update(
                {
                    "policy_revision": 1,
                    "authority": "retained_read_only",
                    "selected_line_ids": current.get("selected_line_ids", []),
                    "terms_digest": current.get("terms_digest"),
                }
            )
            financial.update(app.state.l13_retained_overrides.get(id, {}))
            return httpx.Response(200, json=financial)
        source = validations if "/internal/v2/" in request.url.path else quotes
        return (
            httpx.Response(200, json=source[id])
            if id in source
            else httpx.Response(404)
        )

    app.state.allocation_clients = {
        n: DependencyClient(n, "http://" + n, transport=httpx.MockTransport(upstream))
        for n in ("identity", "catalog", "pricing", "communications")
    }
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://orders"
    )

    def user(org=None, permissions=(), subject=None):
        id = subject or uuid4()
        token = str(id)
        users[token] = {
            "actor": {
                "subject_id": str(id),
                "session_id": "proof",
                "organization_id": str(org) if org else None,
            },
            "roles": ["buyer"],
            "permissions": list(permissions),
            "organizations": [str(org)] if org else [],
            "organization_grants": [],
        }
        return id, {"Authorization": "Bearer " + token}

    def service(name):
        now = datetime.now(timezone.utc)
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {
                    "sub": name,
                    "type": "service",
                    "iss": "beirut-time-identity",
                    "aud": "orders",
                    "iat": now,
                    "exp": now + timedelta(minutes=5),
                },
                private,
                algorithm="RS256",
            )
        }

    async def stock(sale_mode="fixed", seller_type="private"):
        watch = {
            "watch_id": str(uuid4()),
            "listing_id": str(uuid4()),
            "seller_id": str(uuid4()),
            "listing_revision": 1,
            "sale_mode": sale_mode,
            "organization_id": str(uuid4()) if seller_type != "private" else None,
        }
        result = await client.post(
            "/internal/v1/watches/register",
            json=watch,
            headers={**service("catalog"), "Idempotency-Key": str(uuid4())},
        )
        assert result.status_code == 200, result.text
        listings[watch["listing_id"]] = {
            "id": watch["listing_id"],
            "revision": 1,
            "physical_watch_id": watch["watch_id"],
            "seller_type": seller_type,
            "status": "published",
            "is_demo": False,
            "facts": {
                "brand": "Sample",
                "model": "Watch",
                "currency": "USD",
                "price_minor": 500000,
            },
        }
        return watch

    def exact(watch, buyer):
        id = str(uuid4())
        now = datetime.now(timezone.utc)
        quotes[id] = {
            "id": id,
            "owner_id": str(buyer),
            "revision": 1,
            "subject_id": watch["listing_id"],
            "subject_revision": 1,
            "purpose": "purchase",
            "source": "listing",
            "source_verified": True,
            "currency": "USD",
            "price_minor": 500000,
            "buyer_fee_minor": 15000,
            "seller_commission_minor": 25000,
            "seller_net_minor": 475000,
            "rounding": "half_up",
            "minor_unit_exponent": 2,
            "policy": {"schedule_id": "sample-v1"},
            "shipping_minor": 0,
            "tax_minor": 0,
            "payable_minor": 515000,
            "schedule_id": "sample-v1",
            "reviewed_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=15)).isoformat(),
            "sample": True,
        }
        return id

    yield app, client, user, service, stock, exact, quotes, validations
    await client.aclose()
    for c in app.state.allocation_clients.values():
        await c.aclose()
    await app.state.pool.close()
