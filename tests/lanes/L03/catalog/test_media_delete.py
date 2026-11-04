from uuid import UUID, uuid4
import hashlib
import pytest
from .test_listing_lifecycle import draft, photo, headers, image

pytestmark = pytest.mark.asyncio


async def test_remove_cover_is_idempotent_and_cleans_all_variants(api):
    row = await draft(api)
    first = await photo(api, row)
    second = await photo(api, first["listing"])
    row = second["listing"]
    path = f"/v1/seller/listings/{row['id']}/media/{first['asset_id']}"
    key = uuid4().hex
    result = await api.client.delete(path, headers=headers(revision=row["revision"], key=key))
    assert result.status_code == 200
    saved = result.json()
    assert saved["photo_ids"] == [second["asset_id"]] and saved["cover_id"] == second["asset_id"]
    assert (await api.client.delete(path, headers=headers(revision=row["revision"], key=key))).json() == saved
    final = await api.client.delete(
        f"/v1/seller/listings/{row['id']}/media/{second['asset_id']}", headers=headers(revision=saved["revision"])
    )
    assert final.status_code == 200 and final.json()["photo_ids"] == [] and final.json()["cover_id"] is None
    async with api.app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM catalog_media") == 0
        assert await tx.fetchval("SELECT count(*) FROM catalog_media_variants") == 0




async def test_private_image_aggregate_budget_uses_original_measured_bytes(api):
    row = await draft(api)
    asset = await photo(api, row, kind="private_document")
    async with api.app.state.pool.acquire() as tx:
        stored = await tx.fetchrow(
            "SELECT source_bytes,content_hash,private_bytes FROM catalog_media WHERE id=$1", UUID(asset["asset_id"])
        )
    assert stored["source_bytes"] == len(image()) and stored["content_hash"] == hashlib.sha256(image()).hexdigest()
    assert b"private serial" not in stored["private_bytes"]
