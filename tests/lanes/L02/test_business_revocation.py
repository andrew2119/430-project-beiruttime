from uuid import UUID, uuid4
import pytest
from bt_runtime.modules import discover
from conftest import MODULES
from test_identity_modules import business, key


@pytest.mark.asyncio
async def test_staff_privileges_cannot_exceed_supported_business_capabilities(api):
    client, state, pool, _ = api
    identity = (
        await client.post(
            "/v1/businesses",
            json={**business("dealer"), "capabilities": ["servicing"]},
            headers=key(),
        )
    ).json()["id"]
    response = await client.post(
        "/v1/memberships",
        json={
            "business_id": identity,
            "subject_id": str(state["reviewer"]),
            "capabilities": ["business.stock.write"],
            "intervention_scope": "Own business stock only",
            "reason": "Stock access requested",
        },
        headers=key(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "business_capability_required"
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_memberships") == 0
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM identity_access_grants WHERE organization_id=$1",
                UUID(identity),
            )
            == 0
        )


@pytest.mark.asyncio
async def test_business_revocation_and_reactivation_restore_only_current_colleagues(
    api,
):
    client, state, pool, _ = api
    identity = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    members = []
    for subject in (state["reviewer"], state["outsider"]):
        response = await client.post(
            "/v1/memberships",
            json={
                "business_id": identity,
                "subject_id": str(subject),
                "capabilities": ["business.stock.write"],
                "intervention_scope": "Own sample business stock",
                "reason": "Official colleague authorized",
            },
            headers=key(),
        )
        assert response.status_code == 200, response.text
        members.append(response.json())
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
    ).status_code == 200
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM identity_access_grants WHERE organization_id=$1 AND revoked_at IS NULL",
                UUID(identity),
            )
            == 0
        )
    # Revocation must remain possible while the business itself is inactive.
    response = await client.patch(
        "/v1/memberships/" + members[1]["id"],
        json={
            "revision": 1,
            "state": "revoked",
            "reason": "Colleague no longer authorized",
        },
        headers=key(),
    )
    assert response.status_code == 200, response.text
    assert (
        await client.get(f"/v1/businesses/{identity}/memberships")
    ).status_code == 200
    assert (
        await client.patch(
            "/v1/businesses/" + identity,
            json={
                "revision": 2,
                "state": "active",
                "reason": "Business assurance restored",
            },
            headers=key(),
        )
    ).status_code == 200
    async with pool.acquire() as tx:
        grants = await tx.fetch(
            "SELECT subject_id FROM identity_access_grants WHERE organization_id=$1 AND revoked_at IS NULL",
            UUID(identity),
        )
        assert [row["subject_id"] for row in grants] == [state["reviewer"]]
        assert (
            await tx.fetchval(
                "SELECT revoked_at FROM identity_sessions WHERE id=$1",
                state["sessions"][state["outsider"]],
            )
            is not None
        )


@pytest.mark.asyncio
async def test_private_grant_case_and_history_roll_back_with_event_failure(
    api, monkeypatch
):
    client, state, pool, _ = api
    application = uuid4()
    identity = (
        await client.post(
            "/v1/private-reviews",
            json={
                "application_id": str(application),
                "reviewer_id": str(state["reviewer"]),
                "reason": "Independent reviewer assigned",
            },
            headers=key(),
        )
    ).json()["id"]
    state["actor"] = state["reviewer"]
    module = next(
        module for module in discover(MODULES) if module.id == "L02.private-review"
    )
    namespace = module.load("routes.py:verdict").__globals__
    enqueue = namespace["enqueue"]

    async def fail(*args, **kwargs):
        raise OSError("Private transport unavailable")

    monkeypatch.setitem(namespace, "enqueue", fail)
    body = {
        "revision": 1,
        "application_revision": 1,
        "state": "approved",
        "reason": "Identity and possession reviewed",
    }
    headers = key()
    assert (
        await client.post(
            f"/v1/private-reviews/{identity}/verdict", json=body, headers=headers
        )
    ).status_code == 500
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT status FROM identity_private_applications WHERE id=$1",
                application,
            )
            == "pending"
        )
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM identity_access_grants WHERE subject_id=$1 AND role='private_seller'",
                state["applicant"],
            )
            == 0
        )
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM l02_private_review_history WHERE review_id=$1",
                UUID(identity),
            )
            == 1
        )
    monkeypatch.setitem(namespace, "enqueue", enqueue)
    assert (
        await client.post(
            f"/v1/private-reviews/{identity}/verdict", json=body, headers=headers
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_only_a_currently_qualified_non_applicant_can_be_assigned(api):
    client, state, pool, _ = api
    application = uuid4()
    async with pool.acquire() as tx:
        await tx.execute(
            "UPDATE identity_access_grants SET revoked_at=now() WHERE subject_id=$1",
            state["reviewer"],
        )
    response = await client.post(
        "/v1/private-reviews",
        json={
            "application_id": str(application),
            "reviewer_id": str(state["reviewer"]),
            "reason": "Review assignment requested",
        },
        headers=key(),
    )
    assert response.status_code == 403
    response = await client.post(
        "/v1/private-reviews",
        json={
            "application_id": str(application),
            "reviewer_id": str(state["applicant"]),
            "reason": "Review assignment requested",
        },
        headers=key(),
    )
    assert response.status_code == 403
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval("SELECT count(*) FROM identity_private_assignments") == 0
        )
