from uuid import UUID, uuid4
import pytest
from conftest import PERMISSIONS
from test_identity_modules import business, key


@pytest.mark.asyncio
async def test_same_job_title_other_business_and_suspended_grant_are_denied(api):
    client, state, _, _ = api
    identity = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    operator = state["actor"]
    member = (
        await client.post(
            "/v1/memberships",
            json={
                "business_id": identity,
                "subject_id": str(state["reviewer"]),
                "capabilities": ["business.staff.manage"],
                "intervention_scope": "Own business staff records only",
                "reason": "Second colleague authorized",
            },
            headers=key(),
        )
    ).json()
    state.update(
        actor=state["reviewer"],
        permissions=[],
        organization=UUID(identity),
        organizations=[UUID(identity)],
        grants=[
            {
                "organization_id": UUID(identity),
                "roles": ["brand"],
                "permissions": ["business.staff.manage"],
            }
        ],
    )
    assert (
        await client.get(f"/v1/businesses/{identity}/memberships")
    ).status_code == 200
    assert (
        await client.get(f"/v1/businesses/{uuid4()}/memberships")
    ).status_code == 403
    state.update(actor=operator, permissions=PERMISSIONS.copy())
    assert (
        await client.patch(
            "/v1/memberships/" + member["id"],
            json={
                "revision": 1,
                "state": "suspended",
                "reason": "Member scope withdrawn",
            },
            headers=key(),
        )
    ).status_code == 200
    # Even an obsolete provider projection cannot bypass the current local state.
    state.update(actor=state["reviewer"], permissions=[])
    assert (
        await client.get(f"/v1/businesses/{identity}/memberships")
    ).status_code == 403


@pytest.mark.asyncio
async def test_membership_changes_preserve_exact_privilege_snapshots(api):
    client, state, pool, _ = api
    identity = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    member = (
        await client.post(
            "/v1/memberships",
            json={
                "business_id": identity,
                "subject_id": str(state["reviewer"]),
                "capabilities": ["business.stock.write"],
                "qualifications": ["Sample training"],
                "intervention_scope": "Own business stock only",
                "reason": "Colleague authorized",
            },
            headers=key(),
        )
    ).json()
    changed = await client.patch(
        "/v1/memberships/" + member["id"],
        json={
            "revision": 1,
            "state": "active",
            "capabilities": ["business.records.read"],
            "qualifications": [],
            "intervention_scope": "Read own business records only",
            "reason": "Intervention scope restricted",
        },
        headers=key(),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["capabilities"] == ["business.records.read"]
    assert changed.json()["qualifications"] == []
    async with pool.acquire() as tx:
        import json

        history = await tx.fetch(
            "SELECT snapshot FROM l02_membership_history ORDER BY revision"
        )
        assert json.loads(history[0]["snapshot"])["capabilities"] == [
            "business.stock.write"
        ]
        assert json.loads(history[1]["snapshot"])["capabilities"] == [
            "business.records.read"
        ]
