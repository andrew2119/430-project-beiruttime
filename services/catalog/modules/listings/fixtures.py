"""Opt-in demo import through exactly the same authorized application commands."""

import hashlib
import json
import os
import time
from pathlib import Path
from bt_bulkheads import DependencyClient, Unavailable


def quote_operation(demo_key, revision, now=None):
    # Preview receipts expire after fifteen minutes. A ten-minute window and
    # draft revision bound replay without permanently pinning an expired quote.
    return f"{demo_key}-quote-r{revision}-w{int(time.time() if now is None else now) // 600}"


def publication_quote_request(row):
    return {
        "subject_id": row["id"],
        "subject_revision": row["revision"],
        "purpose": "purchase",
        "source": "sample",
        "schedule_id": "usd-v2",
        "price_minor": row["facts"]["price_minor"],
        "currency": "USD",
    }


async def seed(settings):
    if os.getenv("BT_ENVIRONMENT") != "demo" or os.getenv("BT_DEMO_IMPORT_ACK") != "illustrative-stock-only":
        raise RuntimeError("Demonstration import requires its explicit demo-only guard")
    root = Path(os.getenv("BT_DEMO_ROOT", "/app/demo"))
    manifest = json.loads((root / "images-manifest.json").read_text())
    fixtures = json.loads((root / "listings.json").read_text())
    assets = {item["id"]: item for item in manifest["assets"]}
    # Validate every asset BEFORE creating any draft. There is no reset/delete mode.
    from PIL import Image
    from modules.media.images import attribution_matches
    import io

    images = {}
    for asset in assets.values():
        if not all(asset.get(name) for name in ("author", "source_url", "license", "license_url", "local_sha256")):
            raise RuntimeError(f"{asset['id']}: missing attribution")
        content = (root / "watches" / Path(asset["file"]).name).read_bytes()
        if len(content) > 8_000_000 or hashlib.sha256(content).hexdigest() != asset["local_sha256"]:
            raise RuntimeError(f"{asset['id']}: image hash or byte limit")
        if not attribution_matches(content, asset):
            raise RuntimeError(f"{asset['id']}: changed attribution or license metadata")
        try:
            with Image.open(io.BytesIO(content)) as probe:
                if (
                    probe.width * probe.height > 20_000_000
                    or probe.format not in ("JPEG", "PNG")
                    or getattr(probe, "n_frames", 1) != 1
                ):
                    raise ValueError("Image class or pixel limit")
                probe.verify()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise RuntimeError(f"{asset['id']}: failed decoding or decoded image budget") from None
        images[asset["id"]] = content
    base = os.getenv("CATALOG_URL", "http://catalog:8000")
    pricing = os.getenv("PRICING_URL", "http://pricing:8000")
    results = []
    catalog = DependencyClient("catalog-demo-import", base, timeout=15, concurrency=1, failure_threshold=1)
    pricing_client = DependencyClient("pricing-demo-import", pricing, timeout=15, concurrency=1, failure_threshold=1)
    try:
        for item in fixtures["listings"]:
            token = os.environ["BT_DEMO_PRIVATE_TOKEN" if item["seller_type"] == "private" else "BT_DEMO_DEALER_TOKEN"]
            headers = {"Authorization": "Bearer " + token}
            organization = os.getenv("BT_DEMO_DEALER_ORGANIZATION_ID") if item["seller_type"] == "dealer" else None
            if item["seller_type"] == "dealer" and not organization:
                raise RuntimeError("Demonstration dealer requires explicit verified organization selection")
            selected = {"organization_id": organization} if organization else {}
            value = {
                "brand": item["brand"],
                "model": item["model"],
                "reference": item["id"],
                "year": 2020,
                "condition": item["condition"],
                "component_wear": {"case": "Synthetic condition; photograph is illustrative only."},
                "location": item["location"],
                "included": [],
                "no_documents": True,
                "modified": False,
                "modifications": [],
                "ownership_confirmed": True,
                "sale_mode": "auction" if item["sale_mode"] == "auction" else "fixed_price",
                "currency": "USD",
                "price_minor": item["price_minor"],
            }

            async def command(method, path, payload=None, operation="", revision=None, content=None, extra=None):
                response = await catalog.request(
                    method,
                    path,
                    params=selected,
                    json=payload,
                    content=content,
                    headers={
                        **headers,
                        **({"Idempotency-Key": operation} if operation else {}),
                        **({"If-Match": str(revision)} if revision else {}),
                        **(extra or {}),
                    },
                )
                if isinstance(response, Unavailable):
                    raise RuntimeError("Catalog is temporarily unavailable; retry the guarded import")
                response.raise_for_status()
                return response.json()

            created = await command(
                "POST", "/v1/seller/listings", {"facts": value, "demo_key": item["id"]}, item["id"] + ":create"
            )
            # Idempotent create returns its first receipt; reread current canonical state.
            row = await command("GET", f"/v1/seller/listings/{created['id']}")
            if row["status"] == "published":
                results.append(row["id"])
                continue
            asset = assets[item["image_ids"][0]]
            if not row["photo_ids"]:
                uploaded = await command(
                    "POST",
                    f"/v1/seller/listings/{row['id']}/media",
                    operation=item["id"] + ":photo",
                    revision=row["revision"],
                    content=images[asset["id"]],
                    extra={
                        "Content-Type": "application/octet-stream",
                        "X-Media-Kind": "public_photo",
                        "X-Public-Safe": "true",
                        "X-Demo-Asset": asset["id"],
                    },
                )
                row = uploaded["listing"]
            if row["status"] == "publication_pending":
                quote = row["fee_snapshot"]
            else:
                response = await pricing_client.request(
                    "POST",
                    "/v1/quotes",
                    headers={**headers, "Idempotency-Key": quote_operation(item["id"], row["revision"])},
                    json=publication_quote_request(row),
                )
                if isinstance(response, Unavailable):
                    raise RuntimeError("Pricing is temporarily unavailable; retry the guarded import")
                response.raise_for_status()
                quote = response.json()
            result = await command(
                "POST",
                f"/v1/seller/listings/{row['id']}/publish",
                {"fee_quote_id": quote["id"], "rules_version": quote["schedule_id"]},
                item["id"] + ":publish",
                row["revision"],
            )
            results.append(result["id"])
    finally:
        await catalog.aclose()
        await pricing_client.aclose()
    return {"published_listing_ids": results, "count": len(results), "mode": "illustrative-demo"}
