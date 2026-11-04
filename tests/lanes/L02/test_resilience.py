import httpx
import pytest
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from conftest import MODULES
from test_identity_modules import business, key


@pytest.mark.asyncio
async def test_event_intent_failure_rolls_back_business_and_operation(api, monkeypatch):
    client, _, pool, _ = api
    module = next(
        module for module in discover(MODULES) if module.id == "L02.businesses"
    )
    namespace = module.load("routes.py:onboard").__globals__
    enqueue = namespace["enqueue"]

    async def fail(*args, **kwargs):
        raise OSError("Private transport details must not escape")

    monkeypatch.setitem(namespace, "enqueue", fail)
    headers = key()
    response = await client.post("/v1/businesses", json=business(), headers=headers)
    assert response.status_code == 500
    assert "Private transport" not in response.text
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_businesses") == 0
        assert await tx.fetchval("SELECT count(*) FROM l02_business_operations") == 0
        assert await tx.fetchval("SELECT count(*) FROM l02_business_history") == 0
    monkeypatch.setitem(namespace, "enqueue", enqueue)
    assert (
        await client.post("/v1/businesses", json=business(), headers=headers)
    ).status_code == 200


@pytest.mark.asyncio
async def test_acknowledged_business_survives_new_app_and_pool(api, database_url):
    client, _, _, _ = api
    first = await client.post("/v1/businesses", json=business(), headers=key())
    assert first.status_code == 200
    app = create_app(
        Settings(
            database_url=database_url, modules_path=MODULES, service_name="identity"
        )
    )
    app.state.pool = await db.create_pool(database_url)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://restarted"
        ) as restarted:
            records = (await restarted.get("/v1/businesses")).json()["items"]
            assert len(records) == 1
            assert records[0]["id"] == first.json()["id"]
    finally:
        await app.state.pool.close()


@pytest.mark.asyncio
async def test_missing_authority_is_unavailable_and_caller_headers_never_grant(api):
    client, state, pool, app = api
    state["permissions"] = []
    headers = {
        **key(),
        "X-Actor-ID": "operator",
        "X-Organization-ID": "privileged",
        "X-Roles": "operator",
    }
    assert (
        await client.post("/v1/businesses", json=business(), headers=headers)
    ).status_code == 403
    app.dependency_overrides.clear()
    app.state.settings.auth_public_key = ""
    assert (
        await client.post("/v1/businesses", json=business(), headers=headers)
    ).status_code == 503
    async with pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l02_businesses") == 0
