import os
import time
from uuid import uuid4
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from bt_contracts_core.models import EventEnvelope
from .test_listing_lifecycle import ready, publish, headers

pytestmark = pytest.mark.asyncio


async def decide(api, row, action, revision, case=None, event=None, **claims):
    signing = serialization.load_pem_private_key(os.environ["BT_SERVICE_AUTH_PRIVATE_KEY"].encode(), password=None)
    api.app.state.settings.service_auth_public_key = (
        signing.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "trust",
            "type": "service",
            "aud": "catalog",
            "iss": "beirut-time-identity",
            "iat": now,
            "exp": now + 60,
            **claims,
        },
        signing,
        algorithm="RS256",
    )
    case = case or uuid4()
    event = event or EventEnvelope(
        type="trust.moderation.decided.v1",
        source="trust",
        subject=str(case),
        request_id="moderation-proof",
        data={
            "case_id": str(case),
            "target_kind": "listing",
            "target_id": row["id"],
            "action": action,
            "revision": revision,
            "preserve_transaction_duties": True,
        },
    )
    response = await api.client.post(
        "/internal/v1/events", json=event.model_dump(mode="json"), headers={"Authorization": "Bearer " + token}
    )
    return response, event, case


async def test_hide_reinstate_and_old_decision_preserve_physical_registration(api):
    row, asset = await ready(api)
    published = (await publish(api, row)).json()
    first, event, case = await decide(api, row, "hide", 3)
    assert first.status_code == 200 and first.json()["accepted"] is True
    repeated, _, _ = await decide(api, row, "hide", 3, event=event, case=case)
    assert repeated.json()["accepted"] is False
    assert (await api.client.get(f"/v1/listings/{row['id']}/publication")).status_code == 404
    assert (await api.client.get(f"/v1/listings/{row['id']}/photos/{asset}/detail")).status_code == 404
    async with api.app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM catalog_public_listings_v1") == 0
    hidden = (await api.client.get(f"/v1/seller/listings/{row['id']}", headers=headers())).json()
    assert hidden["is_hidden"] and hidden["revision"] == published["revision"]
    assert (await decide(api, row, "reinstate", 2, case=case))[0].status_code == 200
    assert (await api.client.get(f"/v1/listings/{row['id']}/publication")).status_code == 404
    assert (await decide(api, row, "reinstate", 4, case=case))[0].status_code == 200
    assert (await api.client.get(f"/v1/listings/{row['id']}/publication")).status_code == 200
    assert len(api.calls) == 1


async def test_separate_active_holds_are_not_accidentally_cleared(api):
    row, _ = await ready(api)
    assert (await publish(api, row)).status_code == 200
    _, _, first = await decide(api, row, "hide", 1)
    _, _, second = await decide(api, row, "hide", 1)
    await decide(api, row, "reinstate", 2, case=first)
    assert (await api.client.get(f"/v1/listings/{row['id']}/publication")).status_code == 404
    await decide(api, row, "reinstate", 2, case=second)
    assert (await api.client.get(f"/v1/listings/{row['id']}/publication")).status_code == 200


async def test_untrusted_or_wrong_purpose_events_cannot_hide_stock(api):
    row, _ = await ready(api)
    assert (await publish(api, row)).status_code == 200
    for claims in ({"sub": "auction"}, {"type": "access"}, {"aud": "communications"}, {"exp": int(time.time()) - 5}):
        response, _, _ = await decide(api, row, "hide", 1, **claims)
        assert response.status_code in (401, 403)
    assert (await api.client.get(f"/v1/listings/{row['id']}/publication")).status_code == 200


async def test_hidden_listing_is_reportable_only_by_owner_or_real_order_party(api):
    row, _ = await ready(api)
    assert (await publish(api, row)).status_code == 200
    await decide(api, row, "hide", 1)
    path = f"/v1/listings/{row['id']}/report-subject"
    assert (await api.client.get(path, headers=headers())).status_code == 200
    assert (await api.client.get(path, headers=headers("other"))).status_code == 403
    api.order_rows.append(
        {
            "id": str(uuid4()),
            "watch_id": row["physical_watch_id"],
            "buyer_id": api.tokens["other"]["actor"]["subject_id"],
            "seller_id": api.tokens["seller"]["actor"]["subject_id"],
            "state": "awaiting_payment",
        }
    )
    response = await api.client.get(path, headers=headers("other"))
    assert response.status_code == 200 and set(response.json()) == {"id", "seller_id", "organization_id"}


async def test_moderation_hold_blocks_publication_without_allocating(api):
    row, _ = await ready(api)
    await decide(api, row, "hide", 1)
    assert (await publish(api, row)).status_code == 403 and not api.calls
