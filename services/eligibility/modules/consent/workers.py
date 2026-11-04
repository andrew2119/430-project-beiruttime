"""Authenticated durable withdrawal fences; unavailable consumers never acknowledge intent."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
import jwt
from bt_bulkheads import DependencyClient
from bt_events import OutboxRelay


async def run(app, stop):
    key = os.environ.get('BT_EVENT_PRIVATE_KEY','').replace('\\n','\n')
    if not key:
        await stop.wait()
        return
    source = app.state.settings.service_name
    clients = {name: DependencyClient(name,os.environ.get('BT_'+name.upper()+'_API_URL','http://'+name+':8000'),timeout=1.2,concurrency=2)
        for name in ['catalog','orders']}
    def headers(destination):
        now = datetime.now(timezone.utc)
        token = jwt.encode({'iss':app.state.settings.auth_issuer,'aud':destination,'sub':source,'type':'service','iat':now,'exp':now+timedelta(seconds=60)},key,algorithm='RS256')
        return {'Authorization':'Bearer '+token}
    relay = OutboxRelay(app.state.pool,clients,headers=headers,batch_size=8,concurrency=2)
    try:
        while not stop.is_set():
            await relay.tick()
            try:
                await asyncio.wait_for(stop.wait(),timeout=2)
            except TimeoutError:
                pass
    finally:
        for client in clients.values():
            await client.aclose()
