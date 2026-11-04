from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from conftest import PERMISSIONS


def key():
    return {"Idempotency-Key": str(uuid4())}


def business(kind="brand"):
    return {
        "legal_name": "Sample Cedar Watches SAL",
        "public_name": "Sample Cedar Watches",
        "kind": kind,
        "capabilities": ["sales", "servicing"],
        "assurance_reference": "SAMPLE-COMMUNICATION-001",
        "reason": "Approved sample communication record",
        "sample": True,
    }


@pytest.mark.asyncio
async def test_onboarding_public_denied_retry_and_private_fields(api):
    client, state, pool, _ = api
    state["permissions"] = []
    assert (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).status_code == 403
    state["permissions"] = PERMISSIONS.copy()
    headers = key()
    first = await client.post("/v1/businesses", json=business(), headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["authenticated_business"] is True
    assert first.json()["sample"] is True
    assert "assurance_reference" not in first.json()
    assert (
        await client.post("/v1/businesses", json=business(), headers=headers)
    ).json() == first.json()
    assert (
        await client.post(
            "/v1/businesses",
            json={**business(), "public_name": "Changed name"},
            headers=headers,
        )
    ).status_code == 409
    assert (
        await client.post(
            "/v1/businesses",
            json={**business("dealer"), "capabilities": ["customization"]},
            headers=key(),
        )
    ).status_code == 422
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_businesses") == 1
        assert await tx.fetchval("SELECT count(*) FROM outbox") == 2
    identity = first.json()["id"]
    assert (
        await client.patch(
            "/v1/businesses/" + identity,
            json={"revision": 2, "state": "revoked", "reason": "Record withdrawn"},
            headers=key(),
        )
    ).status_code == 409
    assert (
        await client.patch(
            "/v1/businesses/" + identity,
            json={"revision": 1, "state": "revoked", "reason": "Record withdrawn"},
            headers=key(),
        )
    ).status_code == 200
    assert (await client.get("/v1/businesses")).json()["items"] == []
    assert (await client.get("/v1/businesses/" + identity)).json()[
        "authenticated_business"
    ] is False


@pytest.mark.asyncio
async def test_membership_scope_self_intervention_and_history(api):
    client, state, pool, _ = api
    identity = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    payload = {
        "business_id": identity,
        "subject_id": str(state["reviewer"]),
        "capabilities": ["business.stock.write", "business.records.read"],
        "qualifications": ["Sample stock training"],
        "intervention_scope": "Own organization stock only",
        "reason": "Second colleague authorized",
    }
    grant = await client.post("/v1/memberships", json=payload, headers=key())
    assert grant.status_code == 200, grant.text
    membership = grant.json()["id"]
    assert (
        await client.post("/v1/memberships", json=payload, headers=key())
    ).status_code == 409
    assert (
        await client.post(
            "/v1/memberships",
            json={**payload, "subject_id": str(state["actor"])},
            headers=key(),
        )
    ).status_code == 403
    operator = state["actor"]
    state["actor"], state["permissions"] = state["outsider"], []
    assert (
        await client.get(f"/v1/businesses/{identity}/memberships")
    ).status_code == 403
    state["actor"], state["permissions"] = operator, PERMISSIONS.copy()
    for revision, status in [(2, 409), (1, 200), (1, 409)]:
        response = await client.patch(
            "/v1/memberships/" + membership,
            json={
                "revision": revision,
                "state": "suspended",
                "reason": "Intervention scope withdrawn",
            },
            headers=key(),
        )
        assert response.status_code == status, response.text
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_membership_history") == 2
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM outbox WHERE envelope->>'type'='identity.membership-changed.v1'"
            )
            == 6
        )


@pytest.mark.asyncio
async def test_contacts_unverified_delivery_replay_and_wrong_attempts(api):
    client, state, pool, _ = api
    assert (await client.get("/v1/contacts")).json()["revision"] == 0
    payload = {
        "channel": "phone",
        "recipient": "+٩٦١٧١١٢٣٤٥٦",
        "revision": 0,
        "reauthentication": "recent-proof",
    }
    headers = key()
    challenge = await client.post(
        "/v1/contacts/challenges", json=payload, headers=headers
    )
    assert challenge.status_code == 200, challenge.text
    identity = challenge.json()["id"]
    assert (await client.get("/v1/contacts")).json()["pending_challenge"][
        "id"
    ] == identity
    assert (
        await client.post("/v1/contacts/challenges", json=payload, headers=headers)
    ).json() == challenge.json()
    assert (await client.get("/v1/contacts")).json()["phone_verified"] is False
    assert (
        await client.post("/v1/contacts/challenges", json=payload, headers=key())
    ).status_code == 429
    code = (await client.get(f"/v1/contacts/challenges/{identity}/sample-code")).json()[
        "code"
    ]
    verified = await client.post(
        f"/v1/contacts/challenges/{identity}/verify", json={"code": code}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["phone"] == "+96171123456"
    assert verified.json()["phone_verified"] is True
    assert (
        await client.post(
            f"/v1/contacts/challenges/{identity}/verify", json={"code": code}
        )
    ).status_code == 400
    async with pool.acquire() as tx:
        await tx.execute(
            "UPDATE l02_contact_challenges SET created_at=now()-interval '2 minutes'"
        )
    email = await client.post(
        "/v1/contacts/challenges",
        json={
            **payload,
            "channel": "email",
            "recipient": "new@example.test",
            "revision": 2,
        },
        headers=key(),
    )
    assert email.status_code == 200, email.text
    identity = email.json()["id"]
    real = (await client.get(f"/v1/contacts/challenges/{identity}/sample-code")).json()[
        "code"
    ]
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        assert (
            await client.post(
                f"/v1/contacts/challenges/{identity}/verify", json={"code": wrong}
            )
        ).status_code == 400
    assert (
        await client.post(
            f"/v1/contacts/challenges/{identity}/verify", json={"code": real}
        )
    ).status_code == 400
    assert (await client.get("/v1/contacts")).json()["email"] is None
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT attempts FROM l02_contact_challenges WHERE id=$1",
                __import__("uuid").UUID(identity),
            )
            == 5
        )


@pytest.mark.asyncio
async def test_contact_expiry_and_cross_account_and_upstream_outage(api):
    client, state, pool, _ = api
    payload = {
        "channel": "email",
        "recipient": "sample@example.test",
        "revision": 0,
        "reauthentication": "recent-proof",
    }
    app = api[3]
    public = app.state.settings.auth_public_key
    app.state.settings.auth_public_key = ""
    assert (
        await client.post("/v1/contacts/challenges", json=payload, headers=key())
    ).status_code == 503
    app.state.settings.auth_public_key = public
    response = await client.post("/v1/contacts/challenges", json=payload, headers=key())
    identity = response.json()["id"]
    owner = state["actor"]
    state["actor"] = state["outsider"]
    assert (
        await client.get(f"/v1/contacts/challenges/{identity}/sample-code")
    ).status_code == 400
    assert (
        await client.post(
            f"/v1/contacts/challenges/{identity}/verify", json={"code": "123456"}
        )
    ).status_code == 400
    state["actor"] = owner
    code = (await client.get(f"/v1/contacts/challenges/{identity}/sample-code")).json()[
        "code"
    ]
    async with pool.acquire() as tx:
        await tx.execute(
            "UPDATE l02_contact_challenges SET expires_at=$1",
            datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    assert (
        await client.post(
            f"/v1/contacts/challenges/{identity}/verify", json={"code": code}
        )
    ).status_code == 400


@pytest.mark.asyncio
async def test_review_assigned_actor_stale_application_reassignment_and_revoke(api):
    client, state, pool, _ = api
    operator = state["actor"]
    application_id = str(uuid4())
    review = await client.post(
        "/v1/private-reviews",
        json={
            "application_id": application_id,
            "reviewer_id": str(state["reviewer"]),
            "reason": "Independent reviewer assigned",
        },
        headers=key(),
    )
    assert review.status_code == 200, review.text
    identity = review.json()["id"]
    state["actor"] = state["outsider"]
    assert (await client.get("/v1/private-reviews/" + identity)).status_code == 403
    payload = {
        "revision": 1,
        "application_revision": 1,
        "state": "approved",
        "reason": "Identity and possession checked",
    }
    assert (
        await client.post(
            f"/v1/private-reviews/{identity}/verdict", json=payload, headers=key()
        )
    ).status_code == 403
    state["actor"] = state["reviewer"]
    state["revision"] = 2
    assert (
        await client.post(
            f"/v1/private-reviews/{identity}/verdict", json=payload, headers=key()
        )
    ).status_code == 409
    state["revision"], state["complete"] = 1, False
    assert (
        await client.post(
            f"/v1/private-reviews/{identity}/verdict", json=payload, headers=key()
        )
    ).status_code == 409
    state["complete"] = True
    headers = key()
    approved = await client.post(
        f"/v1/private-reviews/{identity}/verdict", json=payload, headers=headers
    )
    assert approved.status_code == 200, approved.text
    assert (
        await client.post(
            f"/v1/private-reviews/{identity}/verdict", json=payload, headers=headers
        )
    ).json() == approved.json()
    state["actor"] = operator
    reassigned = await client.post(
        f"/v1/private-reviews/{identity}/reassign",
        json={
            "revision": 2,
            "reviewer_id": str(state["outsider"]),
            "reason": "Reviewer rotation recorded",
        },
        headers=key(),
    )
    assert reassigned.status_code == 200, reassigned.text
    state["actor"] = state["reviewer"]
    assert (await client.get("/v1/private-reviews/" + identity)).status_code == 403
    state["actor"] = state["outsider"]
    suspended = await client.post(
        f"/v1/private-reviews/{identity}/verdict",
        json={
            **payload,
            "revision": 3,
            "application_revision": 2,
            "state": "suspended",
        },
        headers=key(),
    )
    assert suspended.status_code == 200, suspended.text
    state["actor"] = state["applicant"]
    result = (await client.get("/v1/private-reviews/" + identity)).json()
    assert result["business_privileges"] is False
    assert len(result["history"]) == 4
