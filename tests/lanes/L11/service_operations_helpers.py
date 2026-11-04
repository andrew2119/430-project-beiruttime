def headers(token='brand', key='directory-proof-v1'):
    return {'Authorization': 'Bearer ' + token, 'Idempotency-Key': key}


async def prove_signed_delivery(app, monkeypatch, receiver_status=204):
    import asyncio
    import json
    import httpx
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from bt_bulkheads import DependencyClient
    from bt_contracts_core.models import EventEnvelope
    from bt_events import enqueue

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    monkeypatch.setenv('BT_SERVICE_AUTH_PRIVATE_KEY', pem)
    stop = asyncio.Event()
    verified = []
    def receive(request):
        stop.set()
        assert request.method=='POST' and request.url.path=='/internal/v1/inbox/events'
        claims = jwt.decode(request.headers['Authorization'][7:], private.public_key(), algorithms=['RS256'],
            issuer=app.state.settings.auth_issuer, audience='communications')
        envelope = json.loads(request.content)
        assert claims['type']=='service' and claims['sub']==envelope['source']==app.state.settings.service_name
        assert claims['exp']-claims['iat']==60
        verified.append(envelope['id'])
        return httpx.Response(receiver_status)
    def dependency(name, url, **kwargs):
        if name=='communications':
            kwargs['transport']=httpx.MockTransport(receive)
        return DependencyClient(name, url, **kwargs)
    module = next(module for module in app.state.modules if module.id in ('L11.directory','L11.movement'))
    worker = module.load('dependencies.py:run')
    monkeypatch.setitem(worker.__globals__, 'DependencyClient', dependency)
    event = EventEnvelope(type='service.relay-proof.v1', source=app.state.settings.service_name,
        subject='proof', request_id='proof', data={})
    async with app.state.pool.acquire() as tx:
        async with tx.transaction():
            await enqueue(tx,event,['communications'])
    await asyncio.wait_for(worker(app,stop),3)
    assert verified==[str(event.id)]
    async with app.state.pool.acquire() as tx:
        row=await tx.fetchrow('SELECT delivered_at,attempts,leased_until,available_at>now() AS backoff FROM outbox WHERE event_id=$1',event.id)
        assert (row['delivered_at'] is not None)==(200<=receiver_status<300)
        assert row['attempts']==1 and row['leased_until'] is None
        if receiver_status>=300:
            assert row['backoff'] is True
