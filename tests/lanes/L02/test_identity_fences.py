import asyncio
import hashlib
from uuid import UUID, uuid4
import pytest
from starlette.requests import Request
from bt_contracts_core.errors import PublicError
from bt_runtime.app import db
from service_app.identity import consume_reauthentication
from conftest import PASSWORD, PERMISSIONS
from test_identity_modules import business, key


@pytest.mark.asyncio
async def test_contact_reauthentication_is_recipient_bound_single_use_and_retry_safe(
    api,
):
    client, _, pool, _ = api
    response = await client.post(
        "/v1/accounts/reauthenticate",
        json={
            "password": PASSWORD,
            "purpose": "contact-change",
            "binding": "email:sample@example.test",
        },
    )
    assert response.status_code == 200, response.text
    proof = response.json()["proof"]
    body = {
        "channel": "email",
        "recipient": "sample@example.test",
        "revision": 0,
        "proof": proof,
    }
    wrong = await client.post(
        "/v1/contacts/challenges",
        json={**body, "recipient": "different@example.test"},
        headers=key(),
    )
    assert wrong.status_code == 403
    headers = key()
    first = await client.post("/v1/contacts/challenges", json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert (
        await client.post("/v1/contacts/challenges", json=body, headers=headers)
    ).json() == first.json()
    async with pool.acquire() as tx:
        await tx.execute(
            "UPDATE l02_contact_challenges SET created_at=now()-interval '2 minutes'"
        )
    assert (
        await client.post("/v1/contacts/challenges", json=body, headers=key())
    ).status_code == 403
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_contact_challenges") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,allowed", [(-1, False), (0, False), (1, True)])
async def test_password_proof_exact_database_expiry_boundary(api, offset, allowed):
    client, _, pool, app = api
    response = await client.post(
        "/v1/accounts/reauthenticate",
        json={
            "password": PASSWORD,
            "purpose": "contact-change",
            "binding": "email:sample@example.test",
        },
    )
    proof = response.json()["proof"]
    authorization = response.request.headers["authorization"]
    request = Request(
        {
            "type": "http",
            "app": app,
            "headers": [(b"authorization", authorization.encode())],
        }
    )
    async with db.unit_of_work(pool) as tx:
        await tx.execute(
            "UPDATE identity_reauth_proofs SET expires_at=now()+$2::integer*interval '1 microsecond' WHERE hash=$1",
            hashlib.sha256(proof.encode()).hexdigest(),
            offset,
        )
        if allowed:
            await consume_reauthentication(
                tx,
                request,
                proof,
                purpose="contact-change",
                binding="email:sample@example.test",
            )
        else:
            with pytest.raises(PublicError, match="reauthentication_required"):
                await consume_reauthentication(
                    tx,
                    request,
                    proof,
                    purpose="contact-change",
                    binding="email:sample@example.test",
                )


@pytest.mark.asyncio
async def test_staff_grant_and_suspension_fence_real_session_lineages(api):
    client, state, pool, _ = api
    identity = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    operator = state["actor"]
    colleague = state["reviewer"]
    old_lineage = state["sessions"][colleague]
    grant = await client.post(
        "/v1/memberships",
        json={
            "business_id": identity,
            "subject_id": str(colleague),
            "capabilities": ["business.stock.write", "business.staff.manage"],
            "intervention_scope": "Own sample business only",
            "reason": "Colleague access approved",
        },
        headers=key(),
    )
    assert grant.status_code == 200, grant.text
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT revoked_at FROM identity_sessions WHERE id=$1", old_lineage
            )
            is not None
        )
    state.update(actor=colleague, permissions=[], keep_session=True)
    assert (await client.get("/internal/v1/principal")).status_code == 401
    login = await client.post(
        "/v1/accounts/login",
        json={"email": str(colleague) + "@example.test", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    principal = login.json()["principal"]
    assert principal["permissions"] == []
    scoped = principal["organization_grants"]
    assert len(scoped) == 1 and scoped[0]["organization_id"] == identity
    assert "identity.listings.publish" in scoped[0]["permissions"]
    token = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert (
        await client.get(f"/v1/businesses/{identity}/memberships", headers=token)
    ).status_code == 200
    assert (
        await client.get(f"/v1/businesses/{uuid4()}/memberships", headers=token)
    ).status_code == 403
    state.update(actor=operator, permissions=PERMISSIONS.copy())
    changed = await client.patch(
        "/v1/memberships/" + grant.json()["id"],
        json={
            "revision": 1,
            "state": "suspended",
            "reason": "Intervention scope revoked",
        },
        headers=key(),
    )
    assert changed.status_code == 200, changed.text
    assert (
        await client.get("/internal/v1/principal", headers=token)
    ).status_code == 401


@pytest.mark.asyncio
async def test_private_verdict_case_grant_and_revoke_are_one_atomic_effect(api):
    client, state, pool, _ = api
    application = uuid4()
    assigned = await client.post(
        "/v1/private-reviews",
        json={
            "application_id": str(application),
            "reviewer_id": str(state["reviewer"]),
            "reason": "Independent reviewer assigned",
        },
        headers=key(),
    )
    identity = assigned.json()["id"]
    state["actor"] = state["reviewer"]
    approved = await client.post(
        f"/v1/private-reviews/{identity}/verdict",
        json={
            "revision": 1,
            "application_revision": 1,
            "state": "approved",
            "reason": "Identity and possession evidence reviewed",
        },
        headers=key(),
    )
    assert approved.status_code == 200, approved.text
    async with pool.acquire() as tx:
        case = await tx.fetchrow(
            "SELECT * FROM identity_private_applications WHERE id=$1", application
        )
        grant = await tx.fetchrow(
            "SELECT * FROM identity_access_grants WHERE subject_id=$1 AND role='private_seller' AND revoked_at IS NULL",
            state["applicant"],
        )
        assert case["status"] == "approved" and case["revision"] == 2
        assert grant["organization_id"] is None
        assert grant["permissions"] == ["identity.listings.publish"]
        assert (
            await tx.fetchval(
                "SELECT reviewer_id FROM identity_private_assignments WHERE application_id=$1 AND revoked_at IS NULL",
                application,
            )
            == state["reviewer"]
        )
    suspended = await client.post(
        f"/v1/private-reviews/{identity}/verdict",
        json={
            "revision": 2,
            "application_revision": 2,
            "state": "suspended",
            "reason": "Possession assurance withdrawn",
        },
        headers=key(),
    )
    assert suspended.status_code == 200, suspended.text
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT status FROM identity_private_applications WHERE id=$1",
                application,
            )
            == "suspended"
        )
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM identity_access_grants WHERE subject_id=$1 AND role='private_seller' AND revoked_at IS NULL",
                state["applicant"],
            )
            == 0
        )
        assert (
            await tx.fetchval(
                "SELECT revoked_at FROM identity_sessions WHERE id=$1",
                state["sessions"][state["applicant"]],
            )
            is not None
        )
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM l02_private_review_history WHERE review_id=$1",
                UUID(identity),
            )
            == 3
        )


@pytest.mark.asyncio
async def test_waiting_privileged_command_cannot_resume_after_session_revocation(api):
    client, state, pool, _ = api
    identity = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    async with db.unit_of_work(pool) as tx:
        await tx.fetchrow(
            "SELECT id FROM identity_accounts WHERE id=$1 FOR UPDATE", state["actor"]
        )
        pending = asyncio.create_task(
            client.post(
                "/v1/memberships",
                json={
                    "business_id": identity,
                    "subject_id": str(state["reviewer"]),
                    "capabilities": ["business.records.read"],
                    "intervention_scope": "Own business only",
                    "reason": "Colleague access requested",
                },
                headers=key(),
            )
        )
        await asyncio.sleep(0.05)
        await tx.execute(
            "UPDATE identity_sessions SET revoked_at=now() WHERE subject_id=$1",
            state["actor"],
        )
    response = await pending
    assert response.status_code == 401, response.text
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_memberships") == 0
