"""Authenticated durable delivery; unconfigured destinations remain pending, never simulated."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
import jwt
from bt_bulkheads import DependencyClient
from bt_events import OutboxRelay
from bt_runtime import demo_seed


def destinations(environ=None) -> dict[str, tuple[str, str]]:
    """Each relayed destination's token audience and base URL.

    The demo seed's handoffs to Catalog are relayed only while Identity's seed switch is set to seed or to
    remove (so removal's withdrawals reach Catalog too), to Catalog's own event ingress, which checks that the
    token's audience is Catalog. With the switch unset, as on live, the destination does not exist.
    """
    environ = os.environ if environ is None else environ
    found = {name: (name, environ.get('BT_'+name.upper()+'_API_URL','http://'+name+':8000'))
        for name in ['communications']}
    if demo_seed.mode(environ) in ('seed', 'remove'):
        found[demo_seed.HANDOFF_DESTINATION] = (
            demo_seed.HANDOFF_AUDIENCE, environ.get('BT_CATALOG_API_URL', 'http://catalog:8000'))
    return found


def signer(settings, key: str, audiences: dict[str, str]):
    def headers(destination):
        now = datetime.now(timezone.utc)
        token = jwt.encode({'iss':settings.auth_issuer,'aud':audiences[destination],'sub':settings.service_name,'type':'service','iat':now,'exp':now+timedelta(seconds=60)},key,algorithm='RS256')
        return {'Authorization':'Bearer '+token}
    return headers


async def run(app, stop):
    key = os.environ.get('BT_EVENT_PRIVATE_KEY','').replace('\\n','\n')
    if not key:
        await stop.wait()
        return
    routes = destinations()
    clients = {name: DependencyClient(name,url,timeout=1.2,concurrency=2) for name, (_, url) in routes.items()}
    headers = signer(app.state.settings, key, {name: audience for name, (audience, _) in routes.items()})
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
