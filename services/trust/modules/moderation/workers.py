import asyncio
import os
import time
import jwt
from bt_events import OutboxRelay
from .dependencies import clients


async def run(app, stop):
    upstream=clients(app)
    def headers(destination):
        key=os.getenv('BT_TRUST_SERVICE_PRIVATE_KEY','')
        if not key:
            raise ValueError('Service delivery credential unavailable')
        now=int(time.time())
        token=jwt.encode({'iss':app.state.settings.auth_issuer,'sub':'trust','aud':destination,'type':'service','iat':now,'exp':now+60},key,algorithm='RS256')
        return {'Authorization':'Bearer '+token}
    relay=OutboxRelay(app.state.pool,upstream,headers=headers,batch_size=12,concurrency=3)
    try:
        while not stop.is_set():
            delay=1
            try:
                if os.getenv('BT_TRUST_SERVICE_PRIVATE_KEY',''):
                    await relay.tick()
                else:
                    delay=3  # Missing credentials must not burn durable retry attempts.
            except Exception:
                # Retain durable leases; transient DB failure does not close live clients.
                delay=3
            try:
                await asyncio.wait_for(stop.wait(),timeout=delay)
            except TimeoutError:
                pass
    finally:
        for dependency in upstream.values():
            await dependency.aclose()
