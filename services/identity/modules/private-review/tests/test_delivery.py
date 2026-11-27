from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from bt_runtime.modules import discover

MODULES = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["identity.private-review-assigned.v1", "identity.private-seller-reviewed.v1"],
)
async def test_review_outbox_destination(event_type):
    record = next(m for m in discover(MODULES) if m.id == "L02.private-review").load(
        "routes.py:record"
    )
    statements = []

    class Transaction:
        async def execute(self, sql, *args):
            statements.append((sql, args))

    row = {
        key: uuid4() for key in ("id", "application_id", "applicant_id", "reviewer_id")
    }
    row.update(application_revision=1, revision=1, state="assigned")
    await record(
        Transaction(),
        SimpleNamespace(state=SimpleNamespace(request_id="test-review")),
        uuid4(),
        "test-operation",
        "test-fingerprint",
        row,
        "test reason",
        event_type,
    )
    destinations = [args[1] for sql, args in statements if "INSERT INTO outbox" in sql]
    assert "communications-private-review" in destinations
    assert "communications" not in destinations
    assert ("catalog" in destinations) == (
        event_type == "identity.private-seller-reviewed.v1"
    )


@pytest.mark.asyncio
async def test_review_delivery_uses_scoped_path(monkeypatch):
    client_type = next(
        m for m in discover(MODULES) if m.id == "L02.private-review"
    ).load("workers.py:ReviewClient")
    calls = []

    async def request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))

    monkeypatch.setattr(client_type.__bases__[0], "request", request)
    client = client_type("communications", "http://test", timeout=1.2, concurrency=2)
    try:
        await client.request("POST", "/internal/v1/events", json={"test": True})
        assert calls == [
            (
                "POST",
                "/internal/v1/inbox/private-review/events",
                {"json": {"test": True}},
            )
        ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_pending_review_rows_migrate_without_duplicates(database_url):
    from bt_contracts_core.models import EventEnvelope
    from bt_events import enqueue
    from bt_runtime.app import db

    pool = await db.create_pool(database_url)
    migration = (
        MODULES / "private-review/migrations/L02_0004_review_delivery.sql"
    ).read_text()
    review = EventEnvelope(
        type="identity.private-seller-reviewed.v1",
        source="identity",
        subject="test-subject",
        request_id="test-review",
        data={},
    )
    other = review.model_copy(update={"id": uuid4(), "type": "identity.unknown.v1"})
    try:
        async with db.unit_of_work(pool) as tx:
            await enqueue(tx, review, ["communications", "catalog"])
            await enqueue(tx, other, ["communications"])
            await tx.execute(migration)
            await tx.execute(migration)
            destinations = await tx.fetch(
                "SELECT destination FROM outbox WHERE event_id=$1", review.id
            )
            assert {row["destination"] for row in destinations} == {
                "catalog",
                "communications-private-review",
            }
            assert (
                await tx.fetchval(
                    "SELECT destination FROM outbox WHERE event_id=$1", other.id
                )
                == "communications"
            )
    finally:
        await pool.close()
