"""Authenticated, transactional listing-update inbox against real PostgreSQL."""

import os
import time
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
import asyncpg
import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_contracts_core.models import EventEnvelope

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def events(database_url):
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        signing.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    root = Path(os.getenv("BT_MODULES_PATH", "/app/modules"))
    app = create_app(
        Settings(
            service_name="communications", database_url=database_url, modules_path=root, service_auth_public_key=public
        )
    )
    app.state.pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3)

    def token(**overrides):
        now = int(time.time())
        return jwt.encode(
            {
                "iss": "beirut-time-identity",
                "sub": "catalog",
                "aud": "communications",
                "type": "service",
                "iat": now,
                "exp": now + 60,
                **overrides,
            },
            signing,
            algorithm="RS256",
        )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://communications") as client:
        yield SimpleNamespace(client=client, pool=app.state.pool, token=token)
    await app.state.pool.close()


def update(listing_id=None, revision=1, seller_id=None):
    listing_id = listing_id or uuid4()
    return EventEnvelope(
        type="catalog.listing.draft-saved.v1",
        source="catalog",
        subject=str(listing_id),
        request_id="listing-update-test",
        data={
            "listing_id": str(listing_id),
            "revision": revision,
            "seller_id": str(seller_id or uuid4()),
            "organization_id": None,
            "status": "draft",
            "is_demo": True,
        },
    )


async def send(events, event, token=None):
    return await events.client.post(
        "/internal/v1/seller-workspace/events",
        json=event.model_dump(mode="json"),
        headers={"Authorization": "Bearer " + (token or events.token())},
    )


async def test_delivery_deduplicates_and_older_revision_cannot_regress(events):
    event = update(revision=3)
    first = await send(events, event)
    repeated = await send(events, event)
    assert first.status_code == 200 and first.json()["accepted"] is True
    assert repeated.json()["accepted"] is False
    older = update(listing_id=event.subject, revision=2, seller_id=event.data["seller_id"])
    assert (await send(events, older)).status_code == 200
    async with events.pool.acquire() as tx:
        assert await tx.fetchval("SELECT revision FROM seller_workspace_updates") == 3
        assert await tx.fetchval("SELECT count(*) FROM inbox WHERE consumer='seller-workspace.v1'") == 2


async def test_user_tokens_wrong_producer_and_expired_service_tokens_deny(events):
    event = update()
    for token, code in (
        (events.token(type="access"), 403),
        (events.token(sub="auction"), 403),
        (events.token(aud="orders"), 401),
        (events.token(exp=int(time.time()) - 10), 401),
    ):
        assert (await send(events, event, token)).status_code == code
    assert (
        await events.client.post("/internal/v1/seller-workspace/events", json=event.model_dump(mode="json"))
    ).status_code == 401
    async with events.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM seller_workspace_updates") == 0


async def test_invalid_binding_or_extra_private_data_rolls_back_receipt(events):
    event = update()
    wrong = event.model_copy(update={"subject": str(uuid4())})
    assert (await send(events, wrong)).status_code == 422
    leaked = event.model_copy(update={"data": {**event.data, "private_serial": "must-not-enter-workspace"}})
    assert (await send(events, leaked)).status_code == 422
    async with events.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM seller_workspace_updates") == 0
        assert await tx.fetchval("SELECT count(*) FROM inbox WHERE consumer='seller-workspace.v1'") == 0
