"""Platform capabilities remain independent; an operator title is not a bypass."""

from uuid import uuid4
import pytest
from test_identity_modules import business, key


@pytest.mark.asyncio
async def test_business_manager_needs_no_membership_permission_to_revoke(api):
    client, state, _, _ = api
    state["permissions"] = ["identity.businesses.manage"]
    response = await client.post("/v1/businesses", json=business(), headers=key())
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    changed = await client.patch(
        "/v1/businesses/" + identity,
        json={
            "revision": 1,
            "state": "revoked",
            "reason": "Business assurance withdrawn",
        },
        headers=key(),
    )
    assert changed.status_code == 200, changed.text
    assert (
        await client.post(
            "/v1/memberships",
            json={
                "business_id": identity,
                "subject_id": str(state["reviewer"]),
                "capabilities": ["business.records.read"],
                "intervention_scope": "Own business records only",
                "reason": "Colleague access requested",
            },
            headers=key(),
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_membership_manager_cannot_onboard_or_revoke_businesses(api):
    client, state, _, _ = api
    identity = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    state["permissions"] = ["identity.membership.manage"]
    granted = await client.post(
        "/v1/memberships",
        json={
            "business_id": identity,
            "subject_id": str(state["reviewer"]),
            "capabilities": ["business.records.read"],
            "intervention_scope": "Own business records only",
            "reason": "Colleague access approved",
        },
        headers=key(),
    )
    assert granted.status_code == 200, granted.text
    assert (
        await client.get(f"/v1/businesses/{identity}/memberships")
    ).status_code == 200
    assert (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).status_code == 403
    assert (
        await client.patch(
            "/v1/businesses/" + identity,
            json={
                "revision": 1,
                "state": "revoked",
                "reason": "Business assurance withdrawn",
            },
            headers=key(),
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_assigned_reviewer_needs_no_assignment_or_business_permission(api):
    client, state, _, _ = api
    application = str(uuid4())
    review = (
        await client.post(
            "/v1/private-reviews",
            json={
                "application_id": application,
                "reviewer_id": str(state["reviewer"]),
                "reason": "Independent reviewer assigned",
            },
            headers=key(),
        )
    ).json()["id"]
    state.update(
        actor=state["reviewer"], permissions=["identity.private-seller.review"]
    )
    assert (await client.get("/v1/private-reviews")).status_code == 200
    assert (
        await client.get(f"/v1/private-reviews/{review}/evidence")
    ).status_code == 200
    approved = await client.post(
        f"/v1/private-reviews/{review}/verdict",
        json={
            "revision": 1,
            "application_revision": 1,
            "state": "approved",
            "reason": "Identity and possession evidence reviewed",
        },
        headers=key(),
    )
    assert approved.status_code == 200, approved.text
    assert (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).status_code == 403
    assert (
        await client.post(
            "/v1/private-reviews",
            json={
                "application_id": application,
                "reviewer_id": str(state["outsider"]),
                "reason": "New review requested",
            },
            headers=key(),
        )
    ).status_code == 403
