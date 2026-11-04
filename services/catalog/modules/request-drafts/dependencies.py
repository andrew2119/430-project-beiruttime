import asyncio
import os
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import HTTPException, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import current_principal
from bt_events import OutboxRelay


def clients(app):
    if not hasattr(app.state,'draft_clients'):
        app.state.draft_clients = {name:DependencyClient(name,os.environ.get(env,default),timeout=1.2,concurrency=3)
            for name,env,default in [('identity','BT_IDENTITY_URL','http://identity:8000'),
                ('directory','BT_SERVICE_OPERATIONS_URL','http://service-operations:8000'),
                ('options','BT_CATALOG_URL','http://127.0.0.1:8000'),
                ('communications','BT_COMMUNICATIONS_URL','http://communications:8000')]}
    return app.state.draft_clients


async def principal(request: Request):
    scheme,_,token = request.headers.get('Authorization','').partition(' ')
    if scheme.lower()!='bearer' or not token or len(token)>8192:
        raise HTTPException(401)
    try:
        value = await current_principal(clients(request.app)['identity'],token,request.state.request_id)
    except (ValueError,TypeError):
        raise PublicError('identity_unavailable','Current permissions are unavailable.',status=503) from None
    if isinstance(value,Unavailable):
        raise PublicError('identity_unavailable','Current permissions are unavailable.',status=503)
    if 'buyer' not in value.roles:
        raise AccessDenied('Buyer scope required')
    return value


async def read(request, dependency, path):
    response = await clients(request.app)[dependency].request('GET',path,
        headers={'Authorization':request.headers['Authorization'],'X-Request-ID':request.state.request_id})
    if isinstance(response,Unavailable) or response.status_code!=200:
        return {'status':'unavailable'}
    try:
        value = response.json()
        if not isinstance(value,dict):
            raise ValueError()
        return {'status':'available','data':value}
    except (ValueError,TypeError):
        return {'status':'unavailable'}


def delivery_headers(destination):
    key = os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY','')
    if not key:
        raise RuntimeError('Service signing is not configured')
    now = datetime.now(timezone.utc)
    return {'Authorization':'Bearer '+jwt.encode({'sub':'catalog','type':'service','aud':destination,
        'iss':os.environ.get('BT_AUTH_ISSUER','beirut-time-identity'),'iat':now,'exp':now+timedelta(seconds=60)},key,algorithm='RS256')}


async def run(app,stop):
    dependencies=clients(app)
    relay=OutboxRelay(app.state.pool,{'communications':dependencies['communications']},headers=delivery_headers,batch_size=10,concurrency=2)
    try:
        while not stop.is_set():
            await relay.tick()
            try:
                await asyncio.wait_for(stop.wait(),timeout=3)
            except TimeoutError:
                pass
    finally:
        await asyncio.gather(*(client.aclose() for client in dependencies.values()))
        if getattr(app.state,'draft_clients',None) is dependencies:
            del app.state.draft_clients
