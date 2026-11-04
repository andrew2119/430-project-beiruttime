import asyncio
import httpx
import pytest
from bt_bulkheads import DependencyClient
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue, OutboxRelay


@pytest.mark.asyncio
async def test_module_relay_does_not_lease_another_modules_destination(directory):
    _,app,_=directory
    async with app.state.pool.acquire() as tx:
        async with tx.transaction():
            for destination in ('communications','orders'):
                await enqueue(tx,EventEnvelope(type='service.relay-proof.v1',source='service-operations',subject='proof',request_id='relay-proof',data={}),[destination])
    delivery=DependencyClient('communications','http://communications.fixture',transport=httpx.MockTransport(lambda request:httpx.Response(204)))
    try:
        relay=OutboxRelay(app.state.pool,{'communications':delivery},headers=lambda destination:{})
        assert await relay.tick()==1
        async with app.state.pool.acquire() as tx:
            unrelated=await tx.fetchrow("SELECT attempts,leased_until,delivered_at FROM outbox WHERE destination='orders'")
            assert unrelated['attempts']==0
            assert unrelated['leased_until'] is None and unrelated['delivered_at'] is None
    finally:
        await delivery.aclose()


@pytest.mark.asyncio
async def test_empty_relay_registration_is_a_noop(directory):
    _,app,_=directory
    async with app.state.pool.acquire() as tx:
        async with tx.transaction():
            await enqueue(tx,EventEnvelope(type='service.relay-proof.v1',source='service-operations',subject='proof',request_id='relay-proof',data={}),['orders'])
    assert await OutboxRelay(app.state.pool,{},headers=lambda destination:{}).tick()==0
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT max(attempts) FROM outbox')==0


@pytest.mark.asyncio
async def test_missing_signer_leaves_intent_pending_without_claiming_peer_events(directory,monkeypatch):
    _,app,_=directory
    monkeypatch.delenv('BT_SERVICE_AUTH_PRIVATE_KEY',raising=False)
    async with app.state.pool.acquire() as tx:
        async with tx.transaction():
            await enqueue(tx,EventEnvelope(type='service.relay-proof.v1',source='service-operations',subject='proof',request_id='relay-proof',data={}),['communications'])
    stop=asyncio.Event()
    worker=asyncio.create_task(app.state.modules[0].load('dependencies.py:run')(app,stop))
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(worker,1)
    async with app.state.pool.acquire() as tx:
        row=await tx.fetchrow('SELECT attempts,delivered_at FROM outbox')
        assert row['attempts']==0 and row['delivered_at'] is None


@pytest.mark.asyncio
async def test_directory_service_event_uses_signed_foundation_transport(directory,monkeypatch):
    from L11.service_operations_helpers import prove_signed_delivery
    _,app,_=directory
    await prove_signed_delivery(app,monkeypatch)


@pytest.mark.asyncio
async def test_refused_directory_event_stays_pending_with_bounded_retry(directory,monkeypatch):
    from L11.service_operations_helpers import prove_signed_delivery
    _,app,_=directory
    await prove_signed_delivery(app,monkeypatch,receiver_status=403)
