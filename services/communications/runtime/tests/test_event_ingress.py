import time
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
