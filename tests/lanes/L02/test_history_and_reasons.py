from uuid import UUID, uuid4
import pytest
from test_identity_modules import business, key


@pytest.mark.asyncio
async def test_decision_history_is_bounded_pageable_and_still_owner_private(api):
    client, state, pool, _ = api
    application = uuid4()
    review = (
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
    async with pool.acquire() as tx:
        # Labeled synthetic long-history fixture, not a production/demo import.
        await tx.executemany(
            """INSERT INTO l02_private_review_history(review_id,actor_id,revision,state,reason)
            VALUES($1,$2,$3,'correction','Sample historical correction')""",
            [(UUID(review), state["reviewer"], revision) for revision in range(2, 206)],
        )
        await tx.execute(
            "UPDATE l02_private_reviews SET revision=205,state='correction',application_revision=205 WHERE id=$1",
            UUID(review),
        )
        await tx.execute(
            "UPDATE identity_private_applications SET revision=205,status='correction' WHERE id=$1",
            application,
        )
    state["actor"] = state["applicant"]
    cursor = None
    seen = []
    for size in (100, 100, 5):
        suffix = "" if cursor is None else "?before_revision=" + str(cursor)
        response = await client.get("/v1/private-reviews/" + review + suffix)
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["history"]) == size
        seen.extend(item["revision"] for item in body["history"])
        cursor = body["history_before_revision"]
    assert cursor is None
    assert sorted(seen) == list(range(1, 206))
    assert (
        await client.get(
            "/v1/private-reviews/" + review + "?before_revision=999999999999999999999"
        )
    ).status_code == 422
    state["actor"] = state["outsider"]
    assert (
        await client.get("/v1/private-reviews/" + review + "?before_revision=100")
    ).status_code == 403


@pytest.mark.asyncio
async def test_explanations_cannot_be_blank_whitespace(api):
    client, state, pool, _ = api
    identity = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    assert (
        await client.patch(
            "/v1/businesses/" + identity,
            json={"revision": 1, "state": "revoked", "reason": "     "},
            headers=key(),
        )
    ).status_code == 422
    response = await client.post(
        "/v1/memberships",
        json={
            "business_id": identity,
            "subject_id": str(state["reviewer"]),
            "capabilities": ["business.records.read"],
            "intervention_scope": "     ",
            "reason": "Colleague access approved",
        },
        headers=key(),
    )
    assert response.status_code == 422
    response = await client.post(
        "/v1/private-reviews",
        json={
            "application_id": str(uuid4()),
            "reviewer_id": str(state["reviewer"]),
            "reason": "     ",
        },
        headers=key(),
    )
    assert response.status_code == 422
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_memberships") == 0
        assert await tx.fetchval("SELECT count(*) FROM l02_private_reviews") == 0
        assert (
            await tx.fetchval(
                "SELECT revision FROM l02_businesses WHERE id=$1", UUID(identity)
            )
            == 1
        )
