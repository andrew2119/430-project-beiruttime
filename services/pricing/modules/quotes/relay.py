import asyncio
import os
import time
import jwt
from bt_events import OutboxRelay

class InboxDestination:
    """Versioned destination-path adapter, retaining the same bounded client pool."""
    def __init__(self, client):
        self.client, self.timeout = client, client.timeout

    async def request(self, method, path, **kwargs):
        if method != 'POST' or path != '/internal/v1/events':
            raise ValueError('Unexpected outbox delivery operation')
        return await self.client.request(method, '/internal/v1/inbox/events', **kwargs)


async def run(app, stop):
    # No unauthenticated delivery; missing/expired credentials leave intent durable.
    private = os.environ.get('BT_PRICING_EVENT_PRIVATE_KEY', '')
    token = os.environ.get('BT_COMMUNICATIONS_SERVICE_TOKEN', '')
    def headers(destination):
        current = token
        if private:
            now = int(time.time())
            current = jwt.encode({'sub': 'pricing', 'type': 'service', 'aud': 'communications',
                'iss': app.state.settings.auth_issuer, 'iat': now, 'exp': now + 60}, private, algorithm='RS256')
        return {'Authorization': 'Bearer ' + current}
    relay = OutboxRelay(app.state.pool, {'communications': InboxDestination(app.state.communications)}, headers=headers)
    while not stop.is_set():
        # Missing credentials leave due intent untouched; configuration recovery must
        # not wait behind hours of avoidable unauthorized-delivery backoff.
        if private or token:
            await relay.tick()
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            pass
