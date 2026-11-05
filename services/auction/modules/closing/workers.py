import asyncio
from bt_contracts_core.errors import PublicError
from .service import close
from .reconcile import Sources, reconcile


async def tick(app, sources):
    # Missing/unmerged v2 schema is a real unavailable prerequisite, never a replacement engine.
    rows = await app.state.pool.fetch("""SELECT id,end_version FROM auction_lots WHERE mode='bidding'
        AND ends_at<=clock_timestamp() ORDER BY ends_at,id LIMIT 10""")
    for row in rows:
        try:
            await close(app, row["id"], row["end_version"], "close-worker")
        except PublicError as error:
            if error.status >= 500:
                raise
    pending = await app.state.pool.fetch("""SELECT auction_id FROM l13_auction_closes WHERE state='allocation_pending'
        AND next_attempt_at<=clock_timestamp() AND (lease_until IS NULL OR lease_until<=clock_timestamp())
        ORDER BY next_attempt_at,auction_id LIMIT 5""")
    for row in pending:
        await reconcile(app, sources, row["auction_id"])


async def run(app, stop):
    sources = Sources(app)
    try:
        while not stop.is_set():
            await tick(app, sources)
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass
    finally:
        await sources.aclose()
