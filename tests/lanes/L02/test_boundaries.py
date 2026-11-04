import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from bt_runtime.modules import discover
from conftest import MODULES
from test_identity_modules import business, key


@pytest.mark.asyncio
async def test_concurrent_duplicate_onboarding_is_one_effect(api):
    client, _, pool, _ = api
    headers = key()
    responses = await asyncio.gather(
        *(
            client.post("/v1/businesses", json=business(), headers=headers)
            for _ in range(8)
        )
    )
    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["id"] for response in responses}) == 1
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_business_history") == 1
        assert await tx.fetchval("SELECT count(*) FROM outbox") == 2


@pytest.mark.asyncio
async def test_membership_key_cannot_race_across_businesses(api):
    client, state, pool, _ = api
    first = (
        await client.post("/v1/businesses", json=business(), headers=key())
    ).json()["id"]
    second = (
        await client.post(
            "/v1/businesses",
            json={**business(), "public_name": "Second sample brand"},
            headers=key(),
        )
    ).json()["id"]
    headers = key()

    def payload(identity):
        return {
            "business_id": identity,
            "subject_id": str(state["reviewer"]),
            "capabilities": ["business.records.read"],
            "intervention_scope": "Own records only",
            "reason": "Sample colleague approved",
        }

    responses = await asyncio.gather(
        *(
            client.post("/v1/memberships", json=payload(identity), headers=headers)
            for identity in (first, second)
        )
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_memberships") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,expected", [(-1, 400), (0, 400), (1, 200)])
async def test_contact_exact_expiry_boundary(api, monkeypatch, offset, expected):
    client, _, pool, _ = api
    response = await client.post(
        "/v1/contacts/challenges",
        json={
            "channel": "email",
            "recipient": "sample@example.test",
            "revision": 0,
            "reauthentication": "recent-proof",
        },
        headers=key(),
    )
    identity = response.json()["id"]
    code = (await client.get(f"/v1/contacts/challenges/{identity}/sample-code")).json()[
        "code"
    ]
    now = datetime.now(timezone.utc)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    module = next(module for module in discover(MODULES) if module.id == "L02.contacts")
    monkeypatch.setitem(module.load("routes.py:verify").__globals__, "datetime", Frozen)
    async with pool.acquire() as tx:
        await tx.execute(
            "UPDATE l02_contact_challenges SET expires_at=$2 WHERE id=$1",
            UUID(identity),
            now + timedelta(microseconds=offset),
        )
    response = await client.post(
        f"/v1/contacts/challenges/{identity}/verify", json={"code": code}
    )
    assert response.status_code == expected, response.text


@pytest.mark.asyncio
async def test_business_case_cannot_receive_private_seller_grant(api):
    client, state, pool, _ = api
    state["seller_type"] = "brand"
    response = await client.post(
        "/v1/private-reviews",
        json={
            "application_id": str(uuid4()),
            "reviewer_id": str(state["reviewer"]),
            "reason": "Independent review requested",
        },
        headers=key(),
    )
    assert response.status_code == 403
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_private_reviews") == 0
        assert await tx.fetchval("SELECT count(*) FROM outbox") == 0


@pytest.mark.asyncio
async def test_validation_is_bounded_and_redacts_private_inputs(api):
    client, _, _, _ = api
    private = "DO-NOT-ECHO-PRIVATE-ASSURANCE"
    response = await client.post(
        "/v1/businesses", json={**business(), "reason": private * 30}, headers=key()
    )
    assert response.status_code == 422
    assert private not in response.text
    response = await client.post(
        "/v1/businesses", json={**business(), "kind": "service-provider"}, headers=key()
    )
    assert response.status_code == 422
