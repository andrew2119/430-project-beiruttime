"""Migration proof only: preserve a synthetic legacy reservation, never a demo import."""

import json
from pathlib import Path
from uuid import uuid4
import asyncpg
import pytest


@pytest.mark.asyncio
async def test_demo_label_upgrade_preserves_legacy_commitment_and_outcome(database_owner_url):
    conn = await asyncpg.connect(database_owner_url)
    migration = Path(__file__).resolve().parents[1] / "migrations"
    watch, listing, seller, buyer, order, quote, operation = [uuid4() for _ in range(7)]
    try:
        await conn.execute("CREATE SCHEMA l08_upgrade; SET search_path TO l08_upgrade")
        await conn.execute((migration / "L08_0001_allocation.sql").read_text())
        await conn.execute(
            """INSERT INTO l08_watches(id,listing_id,seller_id,listing_revision,sale_mode,status,source_id,revision)
            VALUES($1,$2,$3,1,'fixed','reserved',$4,2)""",
            watch,
            listing,
            seller,
            order,
        )
        await conn.execute(
            """INSERT INTO l08_orders(id,watch_id,buyer_id,seller_id,quote_id,state,currency,total_minor,deadline)
            VALUES($1,$2,$3,$4,$5,'awaiting_payment','USD',125000,clock_timestamp()+interval '15 minutes')""",
            order,
            watch,
            buyer,
            seller,
            quote,
        )
        outcome = json.dumps(
            {"id": str(operation), "status": "succeeded", "resource_id": str(order), "request_id": "legacy-proof"}
        )
        await conn.execute(
            "INSERT INTO l08_operations(id,actor_key,idempotency_key,digest,result) VALUES($1,$2,'legacy-key',repeat('0',64),$3::jsonb)",
            operation,
            "user:" + str(buyer),
            outcome,
        )
        before_order = dict(await conn.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order))
        before_watch = dict(await conn.fetchrow("SELECT * FROM l08_watches WHERE id=$1", watch))
        before_outcome = await conn.fetchval("SELECT result FROM l08_operations WHERE id=$1", operation)
        await conn.execute((migration / "L08_0002_demo_labels.sql").read_text())
        after_order = dict(await conn.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order))
        after_watch = dict(await conn.fetchrow("SELECT * FROM l08_watches WHERE id=$1", watch))
        assert after_order.pop("listing_id") == listing
        assert after_order.pop("is_demo") is False
        assert after_watch.pop("is_demo") is False
        assert after_order == before_order and after_watch == before_watch
        assert await conn.fetchval("SELECT result FROM l08_operations WHERE id=$1", operation) == before_outcome
        assert await conn.fetchval("SELECT count(*) FROM l08_orders WHERE watch_id=$1", watch) == 1
    finally:
        await conn.close()
