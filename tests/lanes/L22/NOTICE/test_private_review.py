from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from bt_contracts_core.models import EventEnvelope
from bt_runtime.app import db
from service_app.discovery import discover

ROOT = Path(__file__).resolve().parents[4]


def consumer():
    return next(
        m
        for m in discover(ROOT / "services/communications/modules")
        if m.id == "L07.inbox"
    )


def envelope(event_type="identity.private-review-assigned.v1"):
    seller, reviewer = uuid4(), uuid4()
    return EventEnvelope(
        type=event_type,
        source="identity",
        subject=str(seller),
        request_id="test-review",
        data={
            "subject_id": str(seller),
            "reviewer_id": str(reviewer),
            "review_id": str(uuid4()),
            "application_id": str(uuid4()),
            "application_revision": 1,
            "revision": 1,
            "state": "assigned",
        },
    )


def application(pool=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        service_auth_public_key=key.public_key(), auth_issuer="test-issuer"
    )
    app.state.pool = pool
    app.include_router(consumer().load("private_review.py:router"))
    return app, key


def headers(key, subject="identity"):
    now = int(datetime.now(timezone.utc).timestamp())
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": subject,
                "type": "service",
                "aud": "communications",
                "iss": "test-issuer",
                "iat": now,
                "exp": now + 60,
            },
            key,
            algorithm="RS256",
        )
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unknown", "source", "token"])
async def test_unknown_type_and_wrong_source_refused(change):
    app, key = application()
    event = envelope()
    if change == "unknown":
        event = event.model_copy(update={"type": "identity.unknown.v1"})
    if change == "source":
        event = event.model_copy(update={"source": "pricing"})
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/v1/inbox/private-review/events",
            json=event.model_dump(mode="json"),
            headers=headers(
                key, "pricing" if change in {"source", "token"} else "identity"
            ),
        )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["identity.private-review-assigned.v1", "identity.private-seller-reviewed.v1"],
)
async def test_review_recipients_and_replay(database_url, event_type):
    pool = await db.create_pool(database_url)
    app, key = application(pool)
    event = envelope(event_type)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for accepted in (True, False):
                response = await client.post(
                    "/internal/v1/inbox/private-review/events",
                    json=event.model_dump(mode="json"),
                    headers=headers(key),
                )
                assert response.status_code == 200
                assert response.json() == {"accepted": accepted}
        async with pool.acquire() as tx:
            rows = await tx.fetch(
                "SELECT * FROM l07_notices WHERE occurrence_id=$1", str(event.id)
            )
            assert {str(row["recipient_id"]) for row in rows} == {
                event.data["subject_id"],
                event.data["reviewer_id"],
            }
            assert all(row["required"] and not row["sample"] for row in rows)
            assert {row["kind"] for row in rows} == {
                consumer().load("private_review.py:TYPES")[event_type]
            }
            assert (
                await tx.fetchval(
                    "SELECT count(*) FROM l07_notices WHERE kind='payment_required'"
                )
                == 0
            )
    finally:
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["identity.private-review-assigned.v1", "identity.private-seller-reviewed.v1"],
)
async def test_review_projection(event_type):
    notices = []

    class Transaction:
        async def fetchval(self, sql, *args):
            return False

        async def execute(self, sql, *args):
            notices.append(args)

    event = envelope(event_type)
    await consumer().load("private_review.py:store")(Transaction(), event)
    assert {str(args[1]) for args in notices} == {
        event.data["subject_id"],
        event.data["reviewer_id"],
    }
    assert all(args[2] == "identity" and args[3] == str(event.id) for args in notices)
    assert all(
        args[4] == consumer().load("private_review.py:TYPES")[event_type]
        for args in notices
    )
    assert all(args[9] is True and args[10] is False for args in notices)


@pytest.mark.asyncio
@pytest.mark.parametrize("is_seller", [True, False])
async def test_review_destination_rechecks_current_access(is_seller):
    owner, seller, resource = uuid4(), uuid4(), uuid4()
    calls = []
    row = {
        "source": "identity",
        "kind": "case_update",
        "resource_id": resource,
        "resource_owner_id": owner,
        "resource_revision": 2,
    }

    class Transaction:
        async def fetchrow(self, sql, *args):
            return row

    class Acquire:
        async def __aenter__(self):
            return Transaction()

        async def __aexit__(self, *args):
            pass

    class Identity:
        async def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"applicant_id": str(owner if is_seller else seller)},
            )

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                pool=SimpleNamespace(acquire=Acquire), identity=Identity()
            )
        ),
        headers={"Authorization": "Bearer test-access"},
        state=SimpleNamespace(request_id="test-review"),
    )
    result = await consumer().load("routes.py:destination")(uuid4(), request, owner)
    assert result == {
        "url": "/seller/verification" if is_seller else "/operations/verification",
        "historical_revision": 2,
    }
    assert calls == [
        (
            "GET",
            "/v1/private-reviews/" + str(resource),
            {
                "headers": {
                    "Authorization": "Bearer test-access",
                    "X-Request-ID": "test-review",
                }
            },
        )
    ]
