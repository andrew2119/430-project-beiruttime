import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from httpx import ASGITransport, AsyncClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.event_http import build_event_router
from bt_events import EventEnvelope, enqueue


@pytest.mark.asyncio
async def test_event_ingress_requires_service_purpose_audience_and_producer(database_url, tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    settings=Settings(database_url=database_url,service_auth_public_key=public,modules_path=tmp_path)
    app=create_app(settings)
    calls=[]
    async def handler(tx,event):
        calls.append(event.id)
        await enqueue(tx,event,['proof'])
    app.include_router(build_event_router('proof',{'foundation.proof.v1':('identity',handler)}))
    event=EventEnvelope(type='foundation.proof.v1',source='identity',subject='synthetic-proof',request_id='proof',data={})
    def token(**patch):
        return jwt.encode({'sub':'identity','iss':settings.auth_issuer,'aud':settings.service_name,
            'iat':int(time.time()),'exp':int(time.time())+60,'type':'service',**patch},key,algorithm='RS256')
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/internal/v1/events',json=event.model_dump(mode='json'))).status_code==401
            for patch,status in [({'type':'access'},403),({'aud':'other'},401),({'sub':'catalog'},403)]:
                response=await client.post('/internal/v1/events',json=event.model_dump(mode='json'),headers={'Authorization':'Bearer '+token(**patch)})
                assert response.status_code==status
            headers={'Authorization':'Bearer '+token()}
            first=await client.post('/internal/v1/events',json=event.model_dump(mode='json'),headers=headers)
            second=await client.post('/internal/v1/events',json=event.model_dump(mode='json'),headers=headers)
            assert first.json()=={'accepted':True}
            assert second.json()=={'accepted':False}
            assert calls==[event.id]
            async with app.state.pool.acquire() as tx:
                assert await tx.fetchval('SELECT count(*) FROM inbox')==1
                assert await tx.fetchval('SELECT count(*) FROM outbox')==1


@pytest.mark.asyncio
async def test_first_publication_serializes_with_admission(database_url):
    from bt_contracts.auction.core.models import CreateAuction
    from bt_contracts_core.errors import PublicError
    from bt_contracts_core.models import Actor
    from bt_runtime.modules import discover
    from bt_runtime.principal import CurrentPrincipal
    from service_app.engine import AuctionEngine

    modules = Path(os.environ.get('BT_MODULES_PATH', '/app/modules'))
    rules = next(module for module in discover(modules) if module.id == 'L05.a-rules')
    publication = rules.load('events.py:publication')
    listing, seller, watch = (uuid4() for _ in range(3))
    catalog_listing = {'id': str(listing), 'seller_id': str(seller), 'watch_id': str(watch),
                       'seller_organization_id': None, 'revision': 1, 'status': 'published', 'is_demo': False}
    watch_revision = 4

    def watch_state(request, watch_id, listing_id, auction_id):
        # The watch reads as fenced for this auction only after the commitment write.
        revision = dependencies.listing.return_value['revision']
        if dependencies.start_commitment.await_count:
            return {'api_version': 2, 'revision': watch_revision + 1, 'listing_revision': revision,
                    'status': 'fenced', 'source_kind': 'auction_open', 'source_id': str(auction_id),
                    'auction_committed': False}
        return {'api_version': 2, 'revision': watch_revision, 'listing_revision': revision, 'status': 'available'}

    dependencies = SimpleNamespace(
        principal=AsyncMock(return_value=CurrentPrincipal(
            actor=Actor(subject_id=seller, session_id='seller-session'),
            permissions=['identity.listings.publish'])),
        listing=AsyncMock(return_value=catalog_listing),
        fence_state=AsyncMock(side_effect=watch_state),
        bid_admission=AsyncMock(return_value=None),
        start_commitment=AsyncMock(return_value={'status': 'succeeded', 'id': str(uuid4())}),
    )
    engine = AuctionEngine(dependencies)
    now = datetime.now(timezone.utc)
    command = CreateAuction(listing_id=listing, currency='USD', opening_minor=10000,
                            increment_bands=[{'from_minor': 0, 'step_minor': 1000}],
                            starts_at=now, ends_at=now + timedelta(hours=1))
    event = EventEnvelope(type='catalog.listing.published.v1', source='catalog', subject=str(listing),
                          request_id='test-publication', data={'listing_id': str(listing), 'revision': 2,
                          'seller_id': str(seller), 'organization_id': None, 'status': 'published',
                          'is_demo': False})
    async with asyncpg.create_pool(database_url, min_size=2, max_size=2) as pool:
        request = SimpleNamespace(headers={'idempotency-key': 'test-open'},
                                  app=SimpleNamespace(state=SimpleNamespace(pool=pool)),
                                  state=SimpleNamespace(request_id='test-open'))
        async with pool.acquire() as writer:
            # Holding the first connection leaves this exact backend for create().
            async with pool.acquire() as admission:
                admission_pid = admission.get_server_pid()
            pending = None
            try:
                async with writer.transaction():
                    assert await writer.fetchval(
                        'SELECT revision FROM auction_publication_watermarks WHERE listing_id=$1', listing) is None
                    await publication(writer, event)
                    pending = asyncio.create_task(engine.create(request, command))
                    async with asyncio.timeout(5):
                        while not await writer.fetchval('SELECT $1 = ANY(pg_blocking_pids($2))',
                                                        writer.get_server_pid(), admission_pid):
                            if pending.done():
                                await pending  # Propagate an early exception, not a false lock failure.
                                pytest.fail('Admission passed before the first publication committed')
                            await asyncio.sleep(0.01)
                    dependencies.listing.assert_not_awaited()
                    dependencies.fence_state.assert_not_awaited()
                    dependencies.start_commitment.assert_not_awaited()
                with pytest.raises(PublicError, match='^listing_changed$') as denied:
                    await asyncio.wait_for(pending, timeout=5)
                assert denied.value.status == 409
            finally:
                if pending is not None and not pending.done():
                    pending.cancel()
                    try:
                        await pending
                    except asyncio.CancelledError:
                        pass
                elif pending is not None and not pending.cancelled() and pending.exception() is not None:
                    # If polling itself failed, still surface a racing unexpected task failure.
                    error = pending.exception()
                    if not isinstance(error, PublicError) or error.code != 'listing_changed':
                        raise error
            dependencies.bid_admission.assert_not_awaited()
            dependencies.start_commitment.assert_not_awaited()
            assert await writer.fetchval('SELECT count(*) FROM auction_lots WHERE listing_id=$1', listing) == 0
            dependencies.listing.return_value = {**catalog_listing, 'revision': 2}
            outcome = await asyncio.wait_for(engine.create(request, command), timeout=5)
            assert outcome['code'] == 'auction_opened'
            _, admitted, _ = dependencies.start_commitment.await_args.args
            assert admitted['listing_revision'] == 2
            assert await writer.fetchval(
                'SELECT listing_revision FROM auction_lots WHERE listing_id=$1', listing) == 2
