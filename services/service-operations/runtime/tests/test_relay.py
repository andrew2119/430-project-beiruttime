import asyncio
import httpx
import pytest
from bt_runtime.app import db
from bt_events import EventEnvelope, OutboxRelay, enqueue
from bt_bulkheads import DependencyClient


@pytest.mark.asyncio
async def test_relay_fences_fanout_and_recovers_failed_delivery(database_url):
    pool=await db.create_pool(database_url)
    fail=True
    delivered=[]
    async def transport(request):
        # Publication must not retain the claiming row locks across HTTP.
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.fetch('SELECT id FROM outbox WHERE destination=$1 FOR UPDATE NOWAIT',request.url.host)
        if request.url.host=='bad' and fail:
            return httpx.Response(503)
        delivered.append(request.url.host)
        return httpx.Response(200)
    clients={name:DependencyClient(name,f'http://{name}',transport=httpx.MockTransport(transport)) for name in ['good','bad']}
    relay=OutboxRelay(pool,clients,headers=lambda destination:{'Authorization':'Bearer synthetic-contract-proof'})
    event=EventEnvelope(type='foundation.proof.v1',source='identity',subject='proof',request_id='proof',data={})
    try:
        async with db.unit_of_work(pool) as tx:
            await enqueue(tx,event,['good','bad'])
        # Separate pollers cannot both claim the same destination row.
        assert sum(await asyncio.gather(relay.tick(),relay.tick()))==1
        assert delivered==['good']
        async with db.unit_of_work(pool) as tx:
            assert await tx.fetchval('SELECT count(*) FROM outbox WHERE delivered_at IS NOT NULL')==1
            await tx.execute('UPDATE outbox SET available_at=now() WHERE delivered_at IS NULL')
        fail=False
        assert await relay.tick()==1
        assert delivered==['good','bad']
        async with db.unit_of_work(pool) as tx:
            assert await tx.fetchval('SELECT max(attempts) FROM outbox')==2
    finally:
        for client in clients.values():
            await client.aclose()
        await pool.close()
