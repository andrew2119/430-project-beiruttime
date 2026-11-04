import json
from uuid import UUID
import asyncpg
import pytest
from bt_runtime.app import db
from conftest import MODULES
from test_identity_modules import key


@pytest.mark.asyncio
async def test_normal_delivery_is_pending_not_a_fabricated_sent_message(
    api, monkeypatch
):
    client, state, pool, _ = api
    monkeypatch.setenv("BT_CONTACT_SIMULATOR", "0")
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
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    assert response.json()["delivery_mode"] == "delivery_pending"
    assert (
        await client.get(f"/v1/contacts/challenges/{identity}/sample-code")
    ).status_code == 404
    async with pool.acquire() as tx:
        row = await tx.fetchrow(
            "SELECT envelope FROM outbox WHERE envelope->>'type'='identity.contact-challenge.v1'"
        )
        event = json.loads(row["envelope"])
        assert event["data"]["challenge_id"] == identity
        code = event["data"]["code"]
    verified = await client.post(
        f"/v1/contacts/challenges/{identity}/verify", json={"code": code}
    )
    assert verified.status_code == 200
    assert verified.json()["email_sample"] is False
    assert verified.json()["email_verified"] is True
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT delivered_at FROM outbox WHERE event_id=$1", UUID(event["id"])
            )
            is None
        )


@pytest.mark.asyncio
async def test_sample_label_survives_restart_and_v1_schema_upgrade(
    api, database_owner_url
):
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
    verified = await client.post(
        f"/v1/contacts/challenges/{identity}/verify", json={"code": code}
    )
    assert verified.status_code == 200
    assert verified.json()["email_sample"] is True
    # Reconstruct the immediately preceding schema, then apply the additive
    # module migration against the same acknowledged contact/challenge data.
    owner = await asyncpg.connect(database_owner_url)
    try:
        await owner.execute(
            "ALTER TABLE l02_contacts DROP COLUMN email_sample,DROP COLUMN phone_sample"
        )
        await owner.execute(
            "DELETE FROM migration_ledger WHERE step_id='L02.contacts/L02_0002_contact_modes.sql'"
        )
    finally:
        await owner.close()
    await db.migrate(database_owner_url, MODULES)
    current = (await client.get("/v1/contacts")).json()
    assert current["email_verified"] is True
    assert current["email_sample"] is True
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_contacts") == 1
