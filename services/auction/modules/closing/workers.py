import asyncio
from .service import close, recover_assignments
from .follow_up import escalate_overdue
from .reconcile import Sources, reconcile


async def tick(app, sources):
    try:
        await recover_assignments(app)
    except Exception:
        # Assignment recovery remains eligible on the next poll.
        pass
    try:
        await escalate_overdue(app)
    except Exception:
        # The transaction rolls back; later ticks retry the overdue work.
        pass
    # Missing fixed-end kernel schema is unavailable, never a replacement engine.
    # Persist the retry slot before delivery so failure or restart cannot pin a batch.
    rows = await app.state.pool.fetch("""WITH due AS MATERIALIZED (
        SELECT l.id,l.end_version FROM auction_lots l
        LEFT JOIN l13_close_delivery_retries r ON r.auction_id=l.id
        WHERE l.mode IN ('bidding','prebid_pending','prebid_reserved')
        AND l.scheduled_ends_at<=clock_timestamp()
        AND (r.next_attempt_at IS NULL OR r.next_attempt_at<=clock_timestamp())
        AND NOT EXISTS (SELECT 1 FROM l13_auction_closes c WHERE c.auction_id=l.id)
        ORDER BY r.next_attempt_at NULLS FIRST,l.scheduled_ends_at,l.id
        LIMIT 10 FOR UPDATE OF l SKIP LOCKED
    ), claimed AS (
        INSERT INTO l13_close_delivery_retries(auction_id,next_attempt_at)
        SELECT id,clock_timestamp()+interval '30 seconds' FROM due
        ON CONFLICT (auction_id) DO UPDATE SET next_attempt_at=EXCLUDED.next_attempt_at
        RETURNING auction_id
    ) SELECT due.id,due.end_version FROM due JOIN claimed ON claimed.auction_id=due.id""")
    for row in rows:
        try:
            await close(app, row["id"], row["end_version"], "close-worker")
        except Exception:
            # One failed transaction must not block other due records.
            continue
    pending = await app.state.pool.fetch("""SELECT auction_id FROM l13_auction_closes WHERE state='allocation_pending'
        AND next_attempt_at<=clock_timestamp() AND (lease_until IS NULL OR lease_until<=clock_timestamp())
        ORDER BY next_attempt_at,auction_id LIMIT 5""")
    for row in pending:
        try:
            await reconcile(app, sources, row["auction_id"])
        except Exception:
            continue


async def run(app, stop):
    sources = Sources(app)
    try:
        while not stop.is_set():
            try:
                await tick(app, sources)
            except Exception:
                # A failed read remains unavailable until the next bounded poll.
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass
    finally:
        await sources.aclose()
