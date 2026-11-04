"""Connected provider operations: no seeded case or successful endpoint stand-in."""

from uuid import uuid4
import pytest
from conftest import PASSWORD
from test_identity_modules import key


@pytest.mark.asyncio
async def test_real_registration_application_review_and_revocation(api):
    client, state, pool, _ = api
    state["seed_case_on_assign"] = False
    email = "sample-private-" + uuid4().hex + "@example.test"
    registration = await client.post(
        "/v1/accounts/register",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": "Sample private owner",
        },
        headers=key(),
    )
    assert registration.status_code == 201, registration.text
    buyer = registration.json()
    assert buyer["principal"]["roles"] == ["buyer"]
    buyer_headers = {"Authorization": "Bearer " + buyer["access_token"]}
    body = {
        "identity_name": "Sample private owner",
        "contact": email,
        "payout_reference": "DEMO-PRIVATE-OWNER",
        "identity_evidence": "DEMO: synthetic identity reference, not a real identity document",
        "possession_evidence": "DEMO: synthetic possession reference, not a physical watch inspection",
        "expected_revision": 0,
    }
    submitted = await client.post(
        "/v1/private-seller/applications", json=body, headers={**buyer_headers, **key()}
    )
    assert submitted.status_code == 200, submitted.text
    application = submitted.json()["application"]
    assert application["status"] == "pending"
    assigned = await client.post(
        "/v1/private-reviews",
        json={
            "application_id": application["id"],
            "reviewer_id": str(state["reviewer"]),
            "reason": "Independent sample reviewer assigned",
        },
        headers=key(),
    )
    assert assigned.status_code == 200, assigned.text
    review = assigned.json()["id"]
    state.update(
        actor=state["reviewer"], permissions=["identity.private-seller.review"]
    )
    files = await client.get(f"/v1/private-reviews/{review}/evidence")
    assert files.status_code == 200, files.text
    assert len(files.json()["items"]) == 2
    evidence = files.json()["items"][0]["id"]
    download = await client.get(f"/v1/private-reviews/{review}/files/{evidence}")
    assert download.status_code == 200
    assert download.content.startswith(b"DEMO:")
    verdict = {
        "revision": 1,
        "application_revision": 1,
        "state": "approved",
        "reason": "Sample identity and possession references checked",
    }
    approved = await client.post(
        f"/v1/private-reviews/{review}/verdict", json=verdict, headers=key()
    )
    assert approved.status_code == 200, approved.text
    own = await client.get("/v1/private-seller/applications/me", headers=buyer_headers)
    assert own.status_code == 200
    assert own.json()["application"]["status"] == "approved"
    assert own.json()["application"]["reason"] == verdict["reason"]
    principal = (
        await client.get("/internal/v1/principal", headers=buyer_headers)
    ).json()
    assert set(principal["roles"]) == {"buyer", "private_seller"}
    assert principal["permissions"] == ["identity.listings.publish"]
    assert principal["organization_grants"] == []
    owner_proof = await client.get(
        f"/v1/private-seller/applications/{application['id']}/evidence/{evidence}",
        headers=buyer_headers,
    )
    assert owner_proof.status_code == 200
    # The reviewer-only surface remains private even from the applicant.
    assert (
        await client.get(
            f"/v1/private-reviews/{review}/files/{evidence}", headers=buyer_headers
        )
    ).status_code == 403
    suspended = await client.post(
        f"/v1/private-reviews/{review}/verdict",
        json={
            **verdict,
            "revision": 2,
            "application_revision": 2,
            "state": "suspended",
            "reason": "Sample assurance explicitly withdrawn",
        },
        headers=key(),
    )
    assert suspended.status_code == 200, suspended.text
    assert (
        await client.get("/internal/v1/principal", headers=buyer_headers)
    ).status_code == 401
    signed_in = await client.post(
        "/v1/accounts/login", json={"email": email, "password": PASSWORD}
    )
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["principal"]["roles"] == ["buyer"]
    fresh = {"Authorization": "Bearer " + signed_in.json()["access_token"]}
    history = await client.get(f"/v1/private-reviews/{review}", headers=fresh)
    assert history.status_code == 200
    assert len(history.json()["history"]) == 3
    assert history.json()["business_privileges"] is False
    assert history.json()["physical_watch_authentication"] is False
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM outbox WHERE envelope->>'type'='identity.private-seller-submitted.v1'"
            )
            == 1
        )
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM outbox WHERE envelope->>'type'='identity.private-seller-reviewed.v1'"
            )
            == 4
        )
