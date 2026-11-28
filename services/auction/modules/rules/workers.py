import asyncio
import os
import time
import jwt
from bt_bulkheads import DependencyClient
from bt_events import OutboxRelay


DESTINATIONS = {
    'communications': ('communications', '/internal/v1/events'),
    'catalog': ('catalog', '/internal/v1/auction/events'),
    'bid-notices-v2': ('communications', '/internal/v1/events'),
    'auction-timing-v2': ('auction', '/internal/v1/events'),
}


class EventDestination(DependencyClient):
    def __init__(self, destination, service, path):
        url = os.environ.get(service.upper() + '_URL', f'http://{service}:8000')
        super().__init__(destination, url, timeout=1.2, concurrency=2)
        self.path = path

    async def request(self, method, _path, **kwargs):
        return await super().request(method, self.path, **kwargs)


async def relay(app, stop):
    key = os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    if not key:
        # Keep durable intent pending; missing service credentials never mean delivered.
        await stop.wait()
        return
    clients = {name: EventDestination(name, service, path)
               for name, (service, path) in DESTINATIONS.items()}

    def headers(destination):
        now = int(time.time())
        token = jwt.encode({'sub': 'auction', 'type': 'service', 'iss': app.state.settings.auth_issuer,
            'aud': DESTINATIONS[destination][0], 'iat': now, 'exp': now + 60}, key, algorithm='RS256')
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
