import hashlib
import json
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from bt_runtime.modules import discover
from .test_listing_lifecycle import image, headers, draft, quote_snapshot

pytestmark = pytest.mark.asyncio


async def test_demo_import_uses_publication_twice_without_duplicate_stock(api, tmp_path, monkeypatch):
    content = image()
    root = tmp_path / "demo"
    (root / "watches").mkdir(parents=True)
    asset = {
        "id": "IMG-01",
        "file": "watch.jpg",
        "author": "Fixture author",
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "source_url": "https://example.test/fixture",
        "local_sha256": hashlib.sha256(content).hexdigest(),
        "credit": "Synthetic image fixture, CC0 1.0",
    }
    text = (
        f"Author: {asset['author']}\nSource: {asset['source_url']}\nLicense: {asset['license_url']}\nLicense name: {asset['license']}\n"
    ).encode()
    content = content[:2] + b"\xff\xfe" + (len(text) + 2).to_bytes(2, "big") + text + content[2:]
    (root / "watches/watch.jpg").write_bytes(content)
    asset["local_sha256"] = hashlib.sha256(content).hexdigest()
    (root / "images-manifest.json").write_text(json.dumps({"assets": [asset]}))
    items = [
        {
            "id": f"DEMO-WATCH-0{i}",
            "seller_type": "private" if i % 2 else "dealer",
            "brand": "Fixture",
            "model": "Illustrative watch",
            "condition": "Synthetic demonstration condition",
            "location": "Synthetic Beirut",
            "sale_mode": "auction" if i % 2 else "fixed-price",
            "currency": "USD",
            "price_minor": 18000,
            "image_ids": ["IMG-01"],
        }
        for i in range(1, 7)
    ]
    (root / "listings.json").write_text(json.dumps({"listings": items}))
    for name, value in {
        "BT_ENVIRONMENT": "demo",
        "BT_DEMO_IMPORT_ACK": "illustrative-stock-only",
        "BT_DEMO_ROOT": str(root),
        "BT_DEMO_MANIFEST": str(root / "images-manifest.json"),
        "BT_DEMO_PRIVATE_TOKEN": "seller",
        "BT_DEMO_DEALER_TOKEN": "dealer",
        "BT_DEMO_DEALER_ORGANIZATION_ID": api.tokens["dealer"]["actor"]["organization_id"],
        "CATALOG_URL": "http://catalog-demo",
        "PRICING_URL": "http://pricing-demo",
    }.items():
        monkeypatch.setenv(name, value)
    original_client = httpx.AsyncClient
    asgi = httpx.ASGITransport(app=api.app)

    async def transport(request):
        if request.url.host == "pricing-demo":
            body = json.loads(request.content)
            assert "organization_id" not in request.url.params
            assert body["purpose"] == "business_quote" and body["source"] == "sample"
            assert body["schedule_id"] == "sample-v1"
            token = request.headers["Authorization"][7:]
            value = quote_snapshot(
                api, {"id": body["subject_id"], "revision": body["subject_revision"]}, token, uuid4()
            )
            api.quotes["value"] = value
            return httpx.Response(200, json=value)
        return await asgi.handle_async_request(request)

    def client_factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    seed = next(m for m in discover(Path("/app/modules")) if m.id == "L03.listings").load("fixtures.py:seed")
    first = await seed(None)
    second = await seed(None)
    assert first == second and first["count"] == 6
    asset["license"] = "CC BY 4.0"
    (root / "images-manifest.json").write_text(json.dumps({"assets": [asset]}))
    with pytest.raises(RuntimeError, match="IMG-01: changed attribution"):
        await seed(None)
    async with api.app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM catalog_listings WHERE status='published' AND is_demo") == 6
        assert await tx.fetchval("SELECT count(*) FROM catalog_publications") == 6
        for content in await tx.fetch("SELECT content FROM catalog_media_variants"):
            assert b"https://creativecommons.org/publicdomain/zero/1.0/" in content["content"]
    # A public derivative keeps authored credit but never the source serial metadata.
    async with api.app.state.pool.acquire() as tx:
        value = await tx.fetchval("SELECT content FROM catalog_media_variants WHERE variant='detail' LIMIT 1")
        assert b"private serial" not in value and b"Fixture author" in value


async def test_demo_guard_missing_license_and_real_draft_preserved(api, tmp_path, monkeypatch):
    seed = next(m for m in discover(Path("/app/modules")) if m.id == "L03.listings").load("fixtures.py:seed")
    monkeypatch.setenv("BT_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="guard"):
        await seed(None)
    real = await draft(api)
    root = tmp_path / "bad-demo"
    root.mkdir()
    (root / "images-manifest.json").write_text(json.dumps({"assets": [{"id": "IMG-BAD"}]}))
    (root / "listings.json").write_text(json.dumps({"listings": []}))
    monkeypatch.setenv("BT_ENVIRONMENT", "demo")
    monkeypatch.setenv("BT_DEMO_IMPORT_ACK", "illustrative-stock-only")
    monkeypatch.setenv("BT_DEMO_ROOT", str(root))
    with pytest.raises(RuntimeError, match="IMG-BAD: missing attribution"):
        await seed(None)
    response = await api.client.get(f"/v1/seller/listings/{real['id']}", headers=headers())
    assert response.status_code == 200 and not response.json()["is_demo"]
