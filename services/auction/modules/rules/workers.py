import asyncio
import os
import time
import jwt
from bt_bulkheads import DependencyClient
from bt_events import OutboxRelay


async def relay(app, stop):
    key = os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    if not key:
        # Keep durable intent pending; missing service credentials never mean delivered.
        await stop.wait()
        return
    clients = {name: DependencyClient(name, os.environ.get(f'{name.upper()}_URL', f'http://{name}:8000'),
        timeout=1.2, concurrency=2) for name in ('communications', 'catalog')}

    def headers(destination):
        now = int(time.time())
        token = jwt.encode({'sub': 'auction', 'type': 'service', 'iss': app.state.settings.auth_issuer,
            'aud': destination, 'iat': now, 'exp': now + 60}, key, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token}

    try:
        relay = OutboxRelay(app.state.pool, clients, headers=headers, batch_size=8, concurrency=2)
        while not stop.is_set():
            await relay.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=.5)
            except TimeoutError:
                pass
    finally:
        for client in clients.values():
            await client.aclose()
