"""Real PostgreSQL + real HTTP routes; deterministic versioned upstream fixtures."""

import asyncio
import io
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from types import SimpleNamespace
import asyncpg
import httpx
import pytest
import pytest_asyncio
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from PIL import Image
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api(database_url, monkeypatch):
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv(
        "BT_SERVICE_AUTH_PRIVATE_KEY",
        signing.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode(),
    )
    subject, other, org, other_org = uuid4(), uuid4(), uuid4(), uuid4()
    tokens = {
        "seller": {
            "actor": {"subject_id": str(subject), "session_id": "s1"},
            "roles": ["private_seller"],
            "permissions": ["identity.listings.publish"],
        },
        "other": {
            "actor": {"subject_id": str(other), "session_id": "s2"},
            "roles": ["private_seller"],
            "permissions": ["identity.listings.publish"],
        },
        "unverified": {
            "actor": {"subject_id": str(subject), "session_id": "s3"},
            "roles": ["buyer"],
            "permissions": ["catalog.listings.write"],
        },
        "dealer": {
            "actor": {"subject_id": str(subject), "organization_id": str(org), "session_id": "s4"},
            "roles": ["dealer"],
            "permissions": [],
            "organizations": [str(org)],
            "organization_grants": [
                {
                    "organization_id": str(org),
                    "roles": ["dealer"],
                    "permissions": ["business.stock.write", "identity.listings.publish"],
                }
            ],
        },
        "wrong_org": {
            "actor": {"subject_id": str(subject), "organization_id": str(other_org), "session_id": "s5"},
            "roles": ["dealer"],
            "permissions": [],
            "organizations": [str(other_org)],
            "organization_grants": [
                {
                    "organization_id": str(org),
                    "roles": ["dealer"],
                    "permissions": ["business.stock.write", "identity.listings.publish"],
                }
            ],
        },
    }
    quote_id = uuid4()
    quotes = {}
    calls = []
    order_rows = []
    order_result = {}
    fail = {"orders": False, "identity": False}

    async def remote(request):
        dependency = request.url.host
        if fail.get(dependency):
            return httpx.Response(503)
        if dependency == "identity":
            if request.url.path.startswith("/v1/businesses/"):
                return httpx.Response(
                    200,
                    json={
                        "id": str(org),
                        "public_name": "Sample dealer",
                        "kind": "dealer",
                        "capabilities": ["sales"],
                        "state": "active",
                        "revision": 1,
                        "sample": True,
                        "platform_onboarded": True,
                        "authenticated_business": True,
                        "independent_watch_authentication_required": False,
                    },
                )
            name = request.headers.get("Authorization", "")[7:]
            return httpx.Response(200, json=tokens[name]) if name in tokens else httpx.Response(401)
        if dependency == "pricing":
            assert "organization_id" not in request.url.params
            quotes["read_count"] = quotes.get("read_count", 0) + 1
            return httpx.Response(200, json=quotes.get("value", {}))
        if dependency == "orders":
            if request.method == "GET" and request.url.path == "/v1/orders":
                actor = tokens.get(request.headers.get("Authorization", "")[7:], {}).get("actor", {}).get("subject_id")
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            item
                            for item in order_rows
                            if item.get("buyer_id") == actor or item.get("seller_id") == actor
                        ]
                    },
                )
            assert request.url.path == "/internal/v1/watches/register"
            claims = jwt.decode(
                request.headers["Authorization"][7:],
                signing.public_key(),
                algorithms=["RS256"],
                audience="orders",
                issuer="beirut-time-identity",
            )
            assert claims["type"] == "service" and claims["sub"] == "catalog"
            value = json.loads(request.content)
            assert set(value) == {
                "watch_id",
                "listing_id",
                "seller_id",
                "organization_id",
                "listing_revision",
                "sale_mode",
                "is_demo",
            }
            assert value["sale_mode"] in ("fixed", "auction", "seller_base")
            calls.append((request.headers.get("Idempotency-Key"), value))
            return httpx.Response(
                200,
                json=order_result.get("value")
                or {
                    "id": str(uuid4()),
                    "request_id": "orders-proof",
                    "status": "succeeded",
                    "resource_id": value["watch_id"],
                    "watch": {
                        "watch_id": value["watch_id"],
                        "listing_id": value["listing_id"],
                        "sale_mode": value["sale_mode"],
                        "status": "available",
                        "revision": 1,
                        "is_demo": value["is_demo"],
                    },
                },
            )
        return httpx.Response(503)

    app = create_app(
        Settings(
            service_name="catalog",
            database_url=database_url,
            modules_path=Path("/app/modules"),
            request_body_limit=8_500_000,
        )
    )
    app.state.pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    app.state.catalog_clients = {
        name: DependencyClient(name, f"http://{name}", transport=httpx.MockTransport(remote), failure_threshold=50)
        for name in ("identity", "orders", "pricing")
    }
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://catalog")
    yield SimpleNamespace(
        client=client,
        app=app,
        tokens=tokens,
        quotes=quotes,
        quote_id=quote_id,
        calls=calls,
        fail=fail,
        order_rows=order_rows,
        order_result=order_result,
    )
    await client.aclose()
    for upstream in app.state.catalog_clients.values():
        await upstream.aclose()
    await app.state.pool.close()


def headers(token="seller", revision=None, key=None, **extra):
    value = {"Authorization": "Bearer " + token, "Idempotency-Key": key or uuid4().hex, **extra}
    if revision:
        value["If-Match"] = str(revision)
    return value


def facts():
    return {
        "brand": "Seiko",
        "model": "5 Automatic",
        "reference": "SNK-809",
        "year": 2020,
        "condition": "Visible scratches on clasp.",
        "component_wear": {"case": "Light wear", "crystal": "Clean"},
        "location": "Beirut",
        "included": [],
        "no_documents": True,
        "modified": False,
        "modifications": [],
        "ownership_confirmed": True,
        "sale_mode": "fixed_price",
        "currency": "USD",
        "price_minor": 18000,
    }


def image():
    output = io.BytesIO()
    Image.new("RGB", (800, 600), (140, 90, 60)).save(output, "JPEG", exif=b"Exif\x00\x00private serial")
    return output.getvalue()


async def draft(api, token="seller", value=None):
    answer = await api.client.post("/v1/seller/listings", json={"facts": value or facts()}, headers=headers(token))
    assert answer.status_code == 201, answer.text
    return answer.json()


async def photo(api, row, token="seller", kind="public_photo"):
    answer = await api.client.post(
        f"/v1/seller/listings/{row['id']}/media",
        content=image(),
        headers=headers(token, row["revision"], **{"X-Media-Kind": kind, "X-Public-Safe": "true"}),
    )
    assert answer.status_code == 201, answer.text
    return answer.json()


def quote_snapshot(api, row, token="seller", quote_id=None):
    now = datetime.now(timezone.utc)
    return {
        "id": str(quote_id or api.quote_id),
        "owner_id": api.tokens[token]["actor"]["subject_id"],
        "revision": 1,
        "subject_id": row["id"],
        "subject_revision": row["revision"],
        "purpose": "business_quote",
        "source": "sample",
        "source_verified": False,
        "schedule_id": "sample-v1",
        "currency": "USD",
        "price_minor": 18000,
        "minor_unit_exponent": 2,
        "buyer_fee_minor": 540,
        "seller_commission_minor": 900,
        "seller_net_minor": 17100,
        "shipping_minor": 0,
        "tax_minor": 0,
        "payable_minor": 18540,
        "sample": True,
        "rounding": "half_up",
        "fx": None,
        "commission_basis": "price_excluding_buyer_fee_shipping_tax",
        "policy": {
            "buyer_fee_bps": 300,
            "seller_commission_bps": 500,
            "shipping": "sample_zero",
            "tax": "sample_zero",
            "fx": "not_applied",
            "currency_exponents": {"USD": 2, "LBP": 2},
        },
        "created_at": (now - timedelta(seconds=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
        "reviewed_at": None,
    }


async def ready(api):
    row = await draft(api)
    uploaded = await photo(api, row)
    row = uploaded["listing"]
    api.quotes["value"] = quote_snapshot(api, row)
    return row, uploaded["asset_id"]


async def publish(api, row, key=None, token="seller"):
    return await api.client.post(
        f"/v1/seller/listings/{row['id']}/publish",
        json={"fee_quote_id": str(api.quote_id), "rules_version": "sample-v1"},
        headers=headers(token, row["revision"], key),
    )


async def test_draft_persists_complete_fields_and_scopes(api):
    row = await draft(api)
    read = await api.client.get(f"/v1/seller/listings/{row['id']}", headers=headers())
    assert read.json()["facts"] == facts()
    assert (await api.client.get(f"/v1/seller/listings/{row['id']}", headers=headers("other"))).status_code == 403
    assert (await api.client.get("/v1/seller/listings", headers=headers("other"))).json()["items"] == []
    assert (await api.client.get(f"/v1/listings/{row['id']}/publication")).status_code == 404


async def test_draft_idempotency_and_stale_revision(api):
    key = uuid4().hex
    h = headers(key=key)
    first = await api.client.post("/v1/seller/listings", json={"facts": facts()}, headers=h)
    second = await api.client.post("/v1/seller/listings", json={"facts": facts()}, headers=h)
    assert first.json() == second.json()
    changed = facts()
    changed["brand"] = "Omega"
    assert (await api.client.post("/v1/seller/listings", json={"facts": changed}, headers=h)).status_code == 409
    row = first.json()
    path = f"/v1/seller/listings/{row['id']}"
    assert (await api.client.put(path, json={"facts": changed}, headers=headers(revision=1))).status_code == 200
    assert (await api.client.put(path, json={"facts": facts()}, headers=headers(revision=1))).status_code == 409


async def test_incomplete_draft_can_resume_but_not_publish(api):
    answer = await api.client.post("/v1/seller/listings", json={}, headers=headers())
    row = answer.json()
    denied = await publish(api, row)
    assert denied.status_code == 422
    assert "brand" in denied.json()["error"]["details"]["fields"]
    assert not api.calls


async def test_empty_component_notes_remain_an_incomplete_draft(api):
    value = facts()
    value["component_wear"] = {"case": "   "}
    row = await draft(api, value=value)
    row = (await photo(api, row))["listing"]
    answer = await publish(api, row)
    assert answer.status_code == 422 and "component_wear" in answer.json()["error"]["details"]["fields"]
    assert not api.calls


async def test_modified_watch_requires_explicit_components(api):
    value = facts()
    value["modified"] = True
    row = await draft(api, value=value)
    row = (await photo(api, row))["listing"]
    denied = await publish(api, row)
    assert denied.status_code == 422 and "modifications" in denied.json()["error"]["details"]["fields"]


async def test_publication_one_fence_event_and_gallery(api):
    row, asset = await ready(api)
    key = uuid4().hex
    answers = await asyncio.gather(publish(api, row, key), publish(api, row, key))
    assert [a.status_code for a in answers] == [200, 200]
    assert all(a.json()["revision"] == row["revision"] + 1 for a in answers)
    assert len({call[0] for call in api.calls}) == 1
    public = await api.client.get(f"/v1/listings/{row['id']}/publication")
    assert public.status_code == 200 and "fee_snapshot" not in public.json()
    picture = await api.client.get(f"/v1/listings/{row['id']}/photos/{asset}/detail")
    assert picture.status_code == 200
    with Image.open(io.BytesIO(picture.content)) as decoded:
        assert not decoded.getexif() and decoded.size == (800, 600)
    async with api.app.state.pool.acquire() as tx:
        assert (
            await tx.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.listing.published.v1'") == 1
        )
    assert (
        await api.client.put(
            f"/v1/seller/listings/{row['id']}", json={"facts": facts()}, headers=headers(revision=row["revision"] + 1)
        )
    ).status_code == 409


async def test_outage_stays_pending_and_resumes_same_registration(api):
    row, _ = await ready(api)
    api.fail["orders"] = True
    assert (await publish(api, row)).status_code == 503
    assert (await api.client.get(f"/v1/listings/{row['id']}/publication")).status_code == 404
    api.fail["orders"] = False
    assert (await publish(api, row)).status_code == 200


async def test_unverified_or_unavailable_identity_cannot_publish(api):
    row, _ = await ready(api)
    assert (await publish(api, row, token="unverified")).status_code == 403
    api.fail["identity"] = True
    assert (await publish(api, row)).status_code == 503
    assert not api.calls


async def test_media_private_cross_case_and_bad_image_denied(api):
    row = await draft(api)
    doc = await photo(api, row, kind="private_document")
    row = doc["listing"]
    assert (await api.client.get(f"/v1/listings/{row['id']}/photos/{doc['asset_id']}/detail")).status_code == 404
    assert (
        await api.client.get(f"/v1/seller/listings/{row['id']}/media/{doc['asset_id']}", headers=headers("other"))
    ).status_code == 403
    other = await draft(api)
    denied = await api.client.put(
        f"/v1/seller/listings/{other['id']}/gallery",
        json={"photo_ids": [doc["asset_id"]], "cover_id": doc["asset_id"]},
        headers=headers(revision=1),
    )
    assert denied.status_code == 403
    invalid = await api.client.post(
        f"/v1/seller/listings/{row['id']}/media",
        content=b"not an image",
        headers=headers(revision=row["revision"], **{"X-Media-Kind": "public_photo", "X-Public-Safe": "true"}),
    )
    assert invalid.status_code == 422
    async with api.app.state.pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM catalog_media WHERE listing_id=$1", __import__("uuid").UUID(row["id"])
            )
            == 1
        )


async def test_business_kind_is_not_inferred_from_staff_job_title(api):
    api.tokens["dealer"]["organization_grants"][0]["roles"] = ["sales_staff"]
    row = await draft(api, "dealer")
    assert row["seller_type"] == "dealer" and "Sample dealer" in row["seller_label"]
    api.tokens["dealer"]["organization_grants"][0]["permissions"] = ["identity.listings.publish"]
    answer = await api.client.post("/v1/seller/listings", json={}, headers=headers("dealer"))
    assert answer.status_code == 403


async def test_business_permissions_never_union_across_organizations(api):
    row = await draft(api, "dealer")
    assert row["seller_type"] == "dealer"
    assert (await api.client.get("/v1/seller/listings", headers=headers("wrong_org"))).status_code == 403
    assert (await api.client.get(f"/v1/seller/listings/{row['id']}", headers=headers("seller"))).status_code == 403


async def test_public_image_draft_hidden_and_duplicate_upload_replayed(api):
    row = await draft(api)
    key = uuid4().hex
    h = headers(revision=1, key=key, **{"X-Media-Kind": "public_photo", "X-Public-Safe": "true"})
    path = f"/v1/seller/listings/{row['id']}/media"
    first = await api.client.post(path, content=image(), headers=h)
    repeat = await api.client.post(path, content=image(), headers=h)
    assert repeat.json() == first.json()
    asset = first.json()["asset_id"]
    assert (await api.client.get(f"/v1/listings/{row['id']}/photos/{asset}/thumb")).status_code == 404


async def test_demo_disabled_and_finite_money(api):
    assert (
        await api.client.post("/v1/seller/listings", json={"demo_key": "DEMO-WATCH-01"}, headers=headers())
    ).status_code == 403
    for amount in (1.5, True, -1, 10**13):
        value = facts()
        value["price_minor"] = amount
        assert (
            await api.client.post("/v1/seller/listings", json={"facts": value}, headers=headers())
        ).status_code == 422
