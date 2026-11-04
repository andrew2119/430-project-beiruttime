"""Bind publication to the real Pricing v1 owner-private sample quote."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from .test_listing_lifecycle import ready, publish, draft, photo, quote_snapshot, headers

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", str(uuid4())),
        ("subject_id", str(uuid4())),
        ("subject_revision", 999),
        ("purpose", "bid"),
        ("source", "listing"),
        ("source_verified", True),
        ("schedule_id", "unapproved"),
        ("currency", "LBP"),
        ("price_minor", 19000),
        ("sample", False),
        ("buyer_fee_minor", 1.5),
        ("payable_minor", 18000),
    ],
)
async def test_foreign_unbound_or_unbalanced_quote_leaves_draft_editable(api, field, value):
    row, _ = await ready(api)
    api.quotes["value"][field] = value
    assert (await publish(api, row)).status_code == 409
    assert not api.calls
    current = await api.client.get(f"/v1/seller/listings/{row['id']}", headers=headers())
    assert current.json()["status"] == "draft"


async def test_expired_quote_cannot_prepare_new_publication(api):
    row, _ = await ready(api)
    now = datetime.now(timezone.utc)
    api.quotes["value"].update(
        created_at=(now - timedelta(hours=2)).isoformat(), expires_at=(now - timedelta(hours=1)).isoformat()
    )
    assert (await publish(api, row)).status_code == 409
    assert not api.calls


async def test_expiry_is_rechecked_after_obtaining_the_listing_lock(api):
    row, _ = await ready(api)
    api.quotes["value"]["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    async with api.app.state.pool.acquire() as tx:
        async with tx.transaction():
            from uuid import UUID

            await tx.fetchrow("SELECT id FROM catalog_listings WHERE id=$1 FOR UPDATE", UUID(row["id"]))
            task = asyncio.create_task(publish(api, row))
            for _ in range(200):
                if api.quotes.get("read_count"):
                    break
                await asyncio.sleep(0.01)
            assert api.quotes.get("read_count") == 1
            await asyncio.sleep(1.1)
    answer = await task
    assert answer.status_code == 409 and not api.calls
    current = await api.client.get(f"/v1/seller/listings/{row['id']}", headers=headers())
    assert current.json()["status"] == "draft"


async def test_snapshot_stores_only_the_closed_publication_projection(api):
    row, _ = await ready(api)
    api.quotes["value"]["unrelated_private_payload"] = {"maximum_minor": 999999}
    answer = await publish(api, row)
    assert answer.status_code == 200, answer.text
    assert "unrelated_private_payload" not in answer.json()["fee_snapshot"]
    public = await api.client.get(f"/v1/listings/{row['id']}/publication")
    assert "fee_snapshot" not in public.json()


async def test_selected_organization_preserves_expired_token_status(api):
    org = api.tokens["dealer"]["actor"]["organization_id"]
    answer = await api.client.get(f"/v1/seller/listings?organization_id={org}", headers=headers("forged"))
    assert answer.status_code == 401


async def test_business_publication_uses_personal_quote_without_org_context(api):
    row = await draft(api, "dealer")
    row = (await photo(api, row, "dealer"))["listing"]
    api.quotes["value"] = quote_snapshot(api, row, "dealer")
    # The verified selected organization is sent to Identity/Orders, never Pricing.
    answer = await api.client.post(
        f"/v1/seller/listings/{row['id']}/publish?organization_id={api.tokens['dealer']['actor']['organization_id']}",
        json={"fee_quote_id": str(api.quote_id), "rules_version": "sample-v1"},
        headers=headers("dealer", row["revision"]),
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["fee_snapshot"]["sample"] is True
    assert api.calls[0][1]["organization_id"] == api.tokens["dealer"]["actor"]["organization_id"]
