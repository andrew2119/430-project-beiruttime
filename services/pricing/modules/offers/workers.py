"""Leased stable-operation reconciliation; never release a remote watch fence."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4
from bt_runtime.app.db import unit_of_work
from .routes import reconcile_intent


async def tick(app):
    lease = uuid4()
    async with unit_of_work(app.state.pool) as tx:
        rows = await tx.fetch("""WITH due AS (SELECT id FROM l14_offers WHERE state='acceptance_pending'
            AND reconcile_after<=clock_timestamp() AND (reconcile_until IS NULL OR reconcile_until<clock_timestamp())
            ORDER BY reconcile_after,id FOR UPDATE SKIP LOCKED LIMIT 5)
            UPDATE l14_offers o SET reconcile_lease=$1,reconcile_until=clock_timestamp()+interval '30 seconds',
            reconcile_attempts=reconcile_attempts+1 FROM due WHERE o.id=due.id RETURNING o.id,o.reconcile_attempts""", lease)
    for row in rows:
        request = SimpleNamespace(app=app, headers={}, state=SimpleNamespace(request_id=str(uuid4())))
        try:
            await reconcile_intent(request, row['id'])
        except Exception:
            pass  # No success inference, no arbitrary exception/command content in logs.
        async with app.state.pool.acquire() as tx:
            await tx.execute('''UPDATE l14_offers SET reconcile_lease=NULL,reconcile_until=NULL,
                reconcile_after=clock_timestamp()+$3*interval '1 second' WHERE id=$1 AND reconcile_lease=$2''',
                row['id'], lease, min(300, 2 ** min(row['reconcile_attempts'], 8)))
    return len(rows)


async def run(app, stop):
    while not stop.is_set():
        await tick(app)
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except TimeoutError:
            pass
