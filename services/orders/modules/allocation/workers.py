import asyncio
from bt_runtime.app.db import unit_of_work
from bt_contracts_core.models import EventEnvelope
from bt_events import OutboxRelay, enqueue
from .dependencies import clients, delivery_headers
from .repository import audit
from .communications import InboxDestination
from service_app.orders_kernel import lock_watch
from service_app.payment_clock import expiry_decision
from service_app.payment_notices import ensure_payment_notice


async def recover_notices(pool):
    """Recover migrated orders without inventing notice delivery or a clock."""
    async with unit_of_work(pool) as tx:
        rows = await tx.fetch(
            """SELECT o.* FROM l08_orders o WHERE state='awaiting_notification'
            AND currency='USD' AND notified_at IS NULL
            AND NOT EXISTS (SELECT 1 FROM l13_payment_notices n WHERE n.order_id=o.id)
            ORDER BY created_at,id LIMIT 25 FOR UPDATE OF o SKIP LOCKED"""
        )
        for row in rows:
            await ensure_payment_notice(tx, row, "payment-notice-recovery")
        return len(rows)


async def expire(pool):
    async with unit_of_work(pool) as tx:
        # Start/callback/expiry all take the order lock before inspecting attempts.
        rows = await tx.fetch(
            """SELECT * FROM l08_orders WHERE currency='USD' AND state IN ('awaiting_payment','payment_unknown')
            AND deadline<=clock_timestamp() ORDER BY deadline LIMIT 25 FOR UPDATE SKIP LOCKED"""
        )
        for row in rows:
            attempts = await tx.fetch("SELECT state FROM l13_payment_attempts WHERE order_id=$1 FOR UPDATE", row["id"])
            now = await tx.fetchval("SELECT clock_timestamp()")
            decision = expiry_decision(row, attempts, now)
            watch = await lock_watch(tx, row["watch_id"])
            if watch["source_id"] != row["id"] or watch["status"] != "reserved":
                decision = "hold"
            state = "expired_released" if decision == "release" else "expired_fenced"
            revision = row["revision"] + 1
            await tx.execute("UPDATE l08_orders SET state=$2,revision=$3 WHERE id=$1", row["id"], state, revision)
            watch_revision = watch["revision"]
            if decision == "release":
                watch_revision += 1
                await tx.execute(
                    """UPDATE l08_watches SET status='available',source_id=NULL,source_kind=NULL,
                    revision=revision+1 WHERE id=$1""", row["watch_id"],
                )
            await audit(tx, row["id"], "service:orders", "expiry-release" if decision == "release" else "expiry-fence",
                        "Conclusive unpaid expiry" if decision == "release" else "Unknown money retained; operator follow-up within 24 hours", revision)
            await enqueue(tx, EventEnvelope(
                type="orders.commitment-expired.v3", source="orders", subject=str(row["id"]), request_id="expiry",
                data={"order_id": str(row["id"]), "watch_id": str(row["watch_id"]), "listing_id": str(row["listing_id"]),
                      "revision": revision, "watch_revision": watch_revision, "outcome": decision,
                      "automatic_relist": False, "automatic_runner_up": False,
                      "next_action": "none" if decision == "release" else "operator_reconciliation",
                      "follow_up_hours": None if decision == "release" else 24},
            ), ["catalog", "communications"])
        return len(rows)


async def run(app, stop):
    dependencies = clients(app)
    relay = OutboxRelay(
        app.state.pool,
        {"catalog": dependencies["catalog"], "communications": InboxDestination(dependencies["communications"])},
        headers=delivery_headers,
        batch_size=10,
        concurrency=2,
    )
    try:
        while not stop.is_set():
            await recover_notices(app.state.pool)
            await expire(app.state.pool)
            await relay.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass
    finally:
        await asyncio.gather(*(client.aclose() for client in dependencies.values()))
        if getattr(app.state, "allocation_clients", None) is dependencies:
            del app.state.allocation_clients
