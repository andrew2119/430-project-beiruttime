import asyncio
import os
import time
from uuid import UUID
import jwt
from fastapi import HTTPException, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_events import OutboxRelay
from bt_runtime.principal import CurrentPrincipal, current_principal


def clients(app):
    if not hasattr(app.state,'intake_clients'):
        app.state.intake_clients={name:DependencyClient(name,os.getenv('BT_'+name.upper().replace('-','_')+'_URL','http://'+name+':8000'),timeout=1.2,concurrency=4)
            for name in ('identity','orders','service-operations','communications')}
    return app.state.intake_clients


def bearer(request):
    scheme,_,token=request.headers.get('Authorization','').partition(' ')
    if scheme.lower()!='bearer' or not token or len(token)>8192:
        raise HTTPException(401)
    return token


async def principal(request: Request):
    try:
        token=bearer(request)
        selected=request.query_params.get('organization_id')
        if selected:
            try:
                selected=UUID(selected)
            except ValueError:
                raise HTTPException(422) from None
            response=await clients(request.app)['identity'].request('GET',f'/internal/v1/principal?organization_id={selected}',
                headers={'Authorization':'Bearer '+token,'X-Request-ID':request.state.request_id})
            if isinstance(response,Unavailable):
                raise HTTPException(503)
            if response.status_code==401:
                raise HTTPException(401)
            if response.status_code==403:
                raise HTTPException(403)
            if response.status_code!=200:
                raise HTTPException(503)
            result=CurrentPrincipal.model_validate(response.json())
            if result.actor.organization_id!=selected:
                raise HTTPException(403)
        else:
            result=await current_principal(clients(request.app)['identity'],token,request.state.request_id)
    except (ValueError,TypeError,KeyError):
        raise HTTPException(503) from None
    if isinstance(result,Unavailable):
        raise HTTPException(503)
    return result


async def run(app,stop):
    upstream=clients(app)
    def headers(destination):
        key=os.getenv('BT_INTAKE_SERVICE_PRIVATE_KEY','')
        if not key:
            raise ValueError('Service delivery credential unavailable')
        now=int(time.time())
        return {'Authorization':'Bearer '+jwt.encode({'iss':app.state.settings.auth_issuer,'sub':'service-operations','aud':destination,'type':'service','iat':now,'exp':now+60},key,algorithm='RS256')}
    relay=OutboxRelay(app.state.pool,{name:upstream[name] for name in ('orders','communications')},headers=headers,batch_size=12,concurrency=3)
    try:
        while not stop.is_set():
            delay=1
            try:
                if os.getenv('BT_INTAKE_SERVICE_PRIVATE_KEY',''):
                    await relay.tick()
                else:
                    delay=3  # Missing credentials must not burn durable retry attempts.
            except Exception:
                # Retain durable leases; a transient DB failure must not close live clients.
                delay=3
            try:
                await asyncio.wait_for(stop.wait(),timeout=delay)
            except TimeoutError:
                pass
    finally:
        for client in upstream.values():
            await client.aclose()
