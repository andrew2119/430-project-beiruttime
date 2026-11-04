import asyncio
import os
import time
import jwt
from bt_events import OutboxRelay
from .dependencies import clients


class RoutedDestination:
    """A fixed registered event path over the same dependency-owned bulkhead."""

    def __init__(self, client, path):
        self.client, self.path, self.timeout = client, path, client.timeout

    async def request(self, method, _path, **kwargs):
        return await self.client.request(method, self.path, **kwargs)


async def relay(app, stop):
    audiences = {"auction": "auction", "communications-seller-workspace": "communications"}

    def headers(destination):
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "catalog",
                "type": "service",
                "iss": app.state.settings.auth_issuer,
                "aud": audiences[destination],
                "iat": now,
                "exp": now + 60,
            },
            os.environ["BT_SERVICE_AUTH_PRIVATE_KEY"],
            algorithm="RS256",
        )
        return {"Authorization": "Bearer " + token}

    while not stop.is_set():
        if os.getenv("BT_SERVICE_AUTH_PRIVATE_KEY"):
            await OutboxRelay(
                app.state.pool,
                {
                    "auction": clients(app)["auction"],
                    "communications-seller-workspace": RoutedDestination(
                        clients(app)["communications"], "/internal/v1/seller-workspace/events"
                    ),
                },
                headers=headers,
            ).tick()
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass
