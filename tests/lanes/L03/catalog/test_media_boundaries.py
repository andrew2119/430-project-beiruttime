import io
import struct
import zlib
from PIL import Image
import pytest
from .test_listing_lifecycle import headers, image, draft, photo

pytestmark = pytest.mark.asyncio


async def test_gallery_reorder_cover_and_private_document_exclusion(api):
    row = await draft(api)
    first = await photo(api, row)
    second = await photo(api, first["listing"])
    row = second["listing"]
    ids = [second["asset_id"], first["asset_id"]]
    response = await api.client.put(
        f"/v1/seller/listings/{row['id']}/gallery",
        json={"photo_ids": ids, "cover_id": ids[0]},
        headers=headers(revision=row["revision"]),
    )
    assert response.status_code == 200
    assert response.json()["photo_ids"] == ids and response.json()["cover_id"] == ids[0]
    row = response.json()
    document = await photo(api, row, kind="private_document")
    row = document["listing"]
    response = await api.client.put(
        f"/v1/seller/listings/{row['id']}/gallery",
        json={"photo_ids": [document["asset_id"]], "cover_id": document["asset_id"]},
        headers=headers(revision=row["revision"]),
    )
    assert response.status_code == 403


async def test_public_upload_requires_watch_only_confirmation(api):
    row = await draft(api)
    response = await api.client.post(
        f"/v1/seller/listings/{row['id']}/media",
        content=image(),
        headers=headers(revision=1, **{"X-Media-Kind": "public_photo"}),
    )
    assert response.status_code == 422
    async with api.app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM catalog_media") == 0


async def test_measured_byte_and_decoded_pixel_budgets(api):
    row = await draft(api)
    path = f"/v1/seller/listings/{row['id']}/media"
    h = headers(revision=1, **{"X-Media-Kind": "public_photo", "X-Public-Safe": "true"})
    assert (await api.client.post(path, content=b"x" * 8_000_001, headers=h)).status_code == 413
    output = io.BytesIO()
    Image.new("RGB", (10, 10)).save(output, "PNG")
    content = bytearray(output.getvalue())
    content[16:24] = struct.pack(">II", 7000, 7000)
    content[29:33] = struct.pack(">I", zlib.crc32(content[12:29]))
    assert (await api.client.post(path, content=bytes(content), headers=h)).status_code == 422
    async with api.app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM catalog_media") == 0


async def test_file_count_budget_and_failed_upload_no_orphan(api):
    row = await draft(api)
    for _ in range(12):
        row = (await photo(api, row))["listing"]
    response = await api.client.post(
        f"/v1/seller/listings/{row['id']}/media",
        content=image(),
        headers=headers(revision=row["revision"], **{"X-Media-Kind": "public_photo", "X-Public-Safe": "true"}),
    )
    assert response.status_code == 413
    async with api.app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM catalog_media") == 12
        assert await tx.fetchval("SELECT count(*) FROM catalog_media_variants") == 36










async def test_identity_token_and_record_headers_cannot_grant_ownership(api):
    row = await draft(api)
    response = await api.client.get(
        f"/v1/seller/listings/{row['id']}",
        headers={**headers("other"), "X-Actor-ID": str(next(iter(api.tokens.values()))["actor"]["subject_id"])},
    )
    assert response.status_code == 403
    assert (
        await api.client.get(f"/v1/seller/listings/{row['id']}", headers={"Authorization": "Bearer forged"})
    ).status_code == 401


async def test_cancelled_decode_retains_its_native_thread_budget(monkeypatch):
    import asyncio
    import sys
    import threading
    from pathlib import Path
    from bt_runtime.modules import discover
    from bt_contracts_core.errors import PublicError

    module = next(m for m in discover(Path("/app/modules")) if m.id == "L03.media")
    decode = module.load("routes.py:decode")
    routes = sys.modules[decode.__module__]
    started, finish = threading.Event(), threading.Event()

    def slow(content):
        started.set()
        finish.wait(timeout=3)
        return {"decoded": True}

    monkeypatch.setattr(routes, "normalize", slow)
    task = asyncio.create_task(decode(b"bounded fixture"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert routes.DECODERS.locked()
        with pytest.raises(PublicError, match="busy"):
            await decode(b"second fixture")
    finally:
        finish.set()
        for _ in range(100):
            if not routes.DECODERS.locked():
                break
            await asyncio.sleep(0.01)
        assert not routes.DECODERS.locked()
