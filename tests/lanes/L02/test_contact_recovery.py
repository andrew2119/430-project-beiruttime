from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import httpx
import pytest
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from conftest import MODULES
from test_identity_modules import key


@pytest.mark.asyncio
async def test_pending_challenge_survives_new_app_without_exposing_the_code(
    api, database_url
):
    client, _, _, old = api
    challenge = (
        await client.post(
            "/v1/contacts/challenges",
            json={
                "channel": "email",
                "recipient": "sample@example.test",
                "revision": 0,
                "reauthentication": "recent-proof",
            },
            headers=key(),
        )
    ).json()
    app = create_app(
        Settings(
            database_url=database_url,
            modules_path=MODULES,
            service_name="identity",
            auth_public_key=old.state.settings.auth_public_key,
        )
    )
    app.state.pool = await db.create_pool(database_url)
    app.dependency_overrides.update(old.dependency_overrides)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://restarted",
            event_hooks=client.event_hooks,
        ) as fresh:
            result = (await fresh.get("/v1/contacts")).json()
            assert result["pending_challenge"]["id"] == challenge["id"]
            assert "code" not in result["pending_challenge"]
            assert result["email"] is None
            assert result["email_verified"] is False
    finally:
        await app.state.pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,expected", [(-1, 200), (0, 200), (1, 429)])
async def test_request_minute_boundary(api, monkeypatch, offset, expected):
    client, _, pool, _ = api
    body = {
        "channel": "email",
        "recipient": "sample@example.test",
        "revision": 0,
        "reauthentication": "recent-proof",
    }
    await client.post("/v1/contacts/challenges", json=body, headers=key())
    now = datetime.now(timezone.utc)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    module = next(module for module in discover(MODULES) if module.id == "L02.contacts")
    monkeypatch.setitem(
        module.load("routes.py:challenge").__globals__, "datetime", Frozen
    )
    async with pool.acquire() as tx:
        await tx.execute(
            "UPDATE l02_contact_challenges SET created_at=$1",
            now - timedelta(seconds=60) + timedelta(microseconds=offset),
        )
    response = await client.post("/v1/contacts/challenges", json=body, headers=key())
    assert response.status_code == expected, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,expected", [(-1, 200), (0, 200), (1, 429)])
async def test_request_hour_boundary(api, monkeypatch, offset, expected):
    client, _, pool, _ = api
    body = {
        "channel": "email",
        "recipient": "sample@example.test",
        "revision": 0,
        "reauthentication": "recent-proof",
    }
    first = (
        await client.post("/v1/contacts/challenges", json=body, headers=key())
    ).json()
    now = datetime.now(timezone.utc)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    module = next(module for module in discover(MODULES) if module.id == "L02.contacts")
    monkeypatch.setitem(
        module.load("routes.py:challenge").__globals__, "datetime", Frozen
    )
    async with pool.acquire() as tx:
        await tx.execute(
            "UPDATE l02_contact_challenges SET created_at=$1",
            now - timedelta(hours=1) + timedelta(microseconds=offset),
        )
        for _ in range(4):
            await tx.execute(
                """INSERT INTO l02_contact_challenges(id,subject_id,channel,recipient,code_digest,expires_at,created_at,contact_revision)
                SELECT $1,subject_id,channel,recipient,code_digest,expires_at,$2,contact_revision
                FROM l02_contact_challenges WHERE id=$3""",
                uuid4(),
                now - timedelta(minutes=5),
                UUID(first["id"]),
            )
    response = await client.post("/v1/contacts/challenges", json=body, headers=key())
    assert response.status_code == expected, response.text
