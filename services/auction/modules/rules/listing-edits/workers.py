"""Bounded leased settlement of retained listing-edit holds, never new edits."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4
from bt_runtime.app.db import unit_of_work
from .recovery import reconcile_intent


async def tick(app):
    lease = uuid4()
    async with unit_of_work(app.state.pool) as tx:
        rows = await tx.fetch("""WITH due AS (SELECT operation_id FROM auction_listing_edits
            WHERE state='prepared' AND reconcile_after<=clock_timestamp()
            AND (reconcile_until IS NULL OR reconcile_until<clock_timestamp())
            ORDER BY reconcile_after,operation_id FOR UPDATE SKIP LOCKED LIMIT 5)
            UPDATE auction_listing_edits e SET reconcile_lease=$1,reconcile_until=clock_timestamp()+interval '30 seconds',
            reconcile_attempts=reconcile_attempts+1 FROM due WHERE e.operation_id=due.operation_id
            RETURNING e.operation_id,e.reconcile_attempts""", lease)
    for row in rows:
        request = SimpleNamespace(app=app, headers={}, state=SimpleNamespace(request_id=str(uuid4())))
        try:
            await reconcile_intent(request, row['operation_id'])
        except Exception:
            pass  # Retained hold, bounded retry; no private fields in logs.
        async with app.state.pool.acquire() as tx:
            await tx.execute("""UPDATE auction_listing_edits SET reconcile_lease=NULL,reconcile_until=NULL,
                reconcile_after=clock_timestamp()+$3*interval '1 second'
                WHERE operation_id=$1 AND reconcile_lease=$2 AND state='prepared'""",
                row['operation_id'], lease, min(300, 2 ** min(row['reconcile_attempts'], 8)))
    return len(rows)


async def run(app, stop):
    while not stop.is_set():
        await tick(app)
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except TimeoutError:
            pass
