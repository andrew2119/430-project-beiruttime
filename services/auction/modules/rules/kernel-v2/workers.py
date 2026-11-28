"""Recover an already-authorized first-bid fence; NEVER submit a bid."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4
from bt_runtime.app.db import unit_of_work
from service_app.first_bid import prepare


async def tick(app):
    lease = uuid4()
    async with unit_of_work(app.state.pool) as tx:
        rows = await tx.fetch("""WITH due AS (SELECT i.auction_id FROM auction_first_bid_intents i
            WHERE i.status='pending' AND i.reconcile_after<=clock_timestamp()
            AND (i.reconcile_until IS NULL OR i.reconcile_until<clock_timestamp())
            ORDER BY i.reconcile_after,i.auction_id FOR UPDATE SKIP LOCKED LIMIT 5)
            UPDATE auction_first_bid_intents i SET reconcile_lease=$1,reconcile_until=clock_timestamp()+interval '30 seconds',
            reconcile_attempts=reconcile_attempts+1 FROM due WHERE i.auction_id=due.auction_id
            RETURNING i.auction_id,i.subject_id,i.operation_key,i.request_hash,i.reconcile_attempts""", lease)
    for row in rows:
        request = SimpleNamespace(app=app, headers={}, state=SimpleNamespace(request_id=str(uuid4())))
        # This is an operation-owner namespace, not a new user permission grant.
        # Only the immutable retained intent can be replayed; no bid is admitted.
        owner = SimpleNamespace(actor=SimpleNamespace(subject_id=row['subject_id']))
        try:
            await prepare(request, app.state.auction.dependencies, row['auction_id'], owner,
                          row['operation_key'], row['request_hash'])
        except Exception:
            pass  # Durable pending remains; never infer release or log private fields.
        async with app.state.pool.acquire() as tx:
            await tx.execute('''UPDATE auction_first_bid_intents SET reconcile_lease=NULL,reconcile_until=NULL,
                reconcile_after=clock_timestamp()+$3*interval '1 second' WHERE auction_id=$1 AND reconcile_lease=$2''',
                row['auction_id'], lease, min(300, 2 ** min(row['reconcile_attempts'], 8)))
    return len(rows)


async def run(app, stop):
    while not stop.is_set():
        await tick(app)
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except TimeoutError:
            pass
