import asyncio
from bt_runtime.app.db import unit_of_work
from bt_contracts_core.models import EventEnvelope
from bt_events import OutboxRelay, enqueue
from .dependencies import clients, delivery_headers
from .repository import audit


async def expire(pool):
    async with unit_of_work(pool) as tx:
        # Lock and re-read committed state; unknown financial results are never freed.
        rows = await tx.fetch("SELECT id,revision FROM l08_orders WHERE state='awaiting_payment' AND deadline<=clock_timestamp() ORDER BY deadline LIMIT 25 FOR UPDATE SKIP LOCKED")
        for row in rows:
            revision = row['revision']+1
            await tx.execute("UPDATE l08_orders SET state='expired_fenced',revision=$2 WHERE id=$1",row['id'],revision)
            await audit(tx,row['id'],'service:orders','expiry-fence','Unpaid deadline elapsed; reconciliation required',revision)
            await enqueue(tx,EventEnvelope(type='orders.state-changed.v1',source='orders',subject=str(row['id']),
                request_id='expiry',data={'resource_id':str(row['id']),'revision':revision}),['catalog','communications'])
        return len(rows)


async def run(app, stop):
    dependencies = clients(app)
    relay = OutboxRelay(app.state.pool,{key:dependencies[key] for key in ('catalog','communications')},headers=delivery_headers,batch_size=10,concurrency=2)
    try:
        while not stop.is_set():
            await expire(app.state.pool)
            await relay.tick()
            try:
                await asyncio.wait_for(stop.wait(),timeout=2)
            except TimeoutError:
                pass
    finally:
        await asyncio.gather(*(client.aclose() for client in dependencies.values()))
        if getattr(app.state,'allocation_clients',None) is dependencies:
            del app.state.allocation_clients
