import asyncio
import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.app import db
from bt_events import EventEnvelope, enqueue, consume


def test_live_and_error_contract_without_storage():
    app = create_app(Settings(database_url='postgresql://unused/unused'))
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get('/health/live', headers={'X-Request-ID': 'proof-123'})
        assert response.status_code == 200
        assert response.headers['x-request-id'] == 'proof-123'
        missing = client.get('/missing', headers={'X-Request-ID': '<invalid>'})
        assert missing.status_code == 404
        assert missing.json()['error']['code'] == 'not_found'
        assert '<' not in missing.headers['x-request-id']
    finally:
        client.close()


@pytest.mark.asyncio
async def test_readiness_and_ledger(database_url, database_owner_url):
    app = create_app(Settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/health/ready')).json()['status'] == 'ready'
            await db.migrate(database_owner_url)
            assert await db.ready(app.state.pool)
            owner = await asyncpg.connect(database_owner_url)
            try:
                await owner.execute("UPDATE migration_ledger SET checksum=repeat('0',64)")
            finally:
                await owner.close()
            assert (await client.get('/health/ready')).status_code == 503
            with pytest.raises(RuntimeError, match='checksum'):
                await db.migrate(database_owner_url)


@pytest.mark.asyncio
async def test_uow_outbox_and_inbox_rollback(database_url):
    pool = await db.create_pool(database_url)
    event = EventEnvelope(type='foundation.proof.v1', source='identity', subject='demo-proof', request_id='proof', data={})
    async def handler(tx, event):
        await enqueue(tx, event, ['communications'])
    try:
        with pytest.raises(ValueError):
            async with db.unit_of_work(pool) as tx:
                await consume(tx, 'proof', event, handler)
                raise ValueError('rollback')
        async with db.unit_of_work(pool) as tx:
            assert await tx.fetchval('SELECT count(*) FROM inbox') == 0
            assert await tx.fetchval('SELECT count(*) FROM outbox') == 0
        async def attempt():
            async with db.unit_of_work(pool) as tx:
                return await consume(tx, 'proof', event, handler)
        assert sum(await asyncio.gather(attempt(), attempt())) == 1
        async with db.unit_of_work(pool) as tx:
            assert await tx.fetchval('SELECT count(*) FROM outbox') == 1
    finally:
        await pool.close()
