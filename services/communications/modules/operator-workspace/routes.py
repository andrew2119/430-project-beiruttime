import os
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_runtime.principal import current_principal, require_scope

router=APIRouter(prefix='/v1/operator-workspace',tags=['operator workspace'])
QUEUES={
 'verification':{'permission':'identity.private-seller.review','route':'/operations/verification','service':'identity','path':'/v1/private-reviews','release':'available'},
 'moderation':{'permission':'moderation.review','route':'/operations/moderation','service':'trust','path':'/v1/moderation/cases','release':'available'},
 'inspection':{'permission':'authentication.review','route':'/operations/dashboard/queues/inspection','release':'awaiting_prerequisite','prerequisites':['actual_custody','expert_assignment']},
 'disputes':{'permission':'disputes.review','route':'/operations/dashboard/queues/disputes','release':'awaiting_prerequisite','prerequisites':['received_order','open_dispute','reviewer_assignment']},
 'quality':{'permission':'quality.review','route':'/operations/dashboard/queues/quality','release':'awaiting_prerequisite','prerequisites':['authorized_work','quality_assignment']}
}


def clients(app):
    if not hasattr(app.state,'operator_workspace_clients'):
        app.state.operator_workspace_clients={name:DependencyClient(name,os.getenv('BT_'+name.upper()+'_URL','http://'+name+':8000'),timeout=1.2,concurrency=3) for name in ('identity','trust')}
    return app.state.operator_workspace_clients


def bearer(request):
    scheme,_,token=request.headers.get('Authorization','').partition(' ')
    if scheme.lower()!='bearer' or not token or len(token)>8192:
        raise HTTPException(401)
    return token


async def principal(request:Request):
    try:
        p=await current_principal(clients(request.app)['identity'],bearer(request),request.state.request_id)
    except (ValueError,TypeError,KeyError):
        raise HTTPException(503) from None
    if isinstance(p,Unavailable):
        raise HTTPException(503)
    if 'operator' not in p.roles:
        raise HTTPException(403)
    return p


async def read_queue(key,request,p):
    definition=QUEUES[key]
    base={'id':key,'route':definition['route'],'commands':False,'items':[],'prerequisites':definition.get('prerequisites',[])}
    if definition['permission'] not in p.permissions:
        return {**base,'state':'denied'}
    if definition['release']=='awaiting_prerequisite':
        return {**base,'state':'awaiting_prerequisite'}
    response=await clients(request.app)[definition['service']].request('GET',definition['path'],headers={'Authorization':'Bearer '+bearer(request),'X-Request-ID':request.state.request_id})
    if not isinstance(response,Unavailable) and response.status_code==401:
        raise HTTPException(401)
    if isinstance(response,Unavailable) or response.status_code not in (200,403):
        return {**base,'state':'unavailable'}
    if response.status_code==403:
        return {**base,'state':'denied'}
    try:
        items=response.json()['items']
        if not isinstance(items,list) or len(items)>100:
            raise ValueError('Invalid queue contract')
        # Queue previews never contain evidence, identity documents or decision notes.
        safe=[]
        for item in items:
            if not isinstance(item,dict) or 'id' not in item or 'revision' not in item:
                raise ValueError('Invalid queue contract')
            safe.append({'id':item['id'],'revision':item['revision'],
                'status':item.get('status',item.get('state','unknown')),
                **({'created_at':item['created_at']} if 'created_at' in item else {})})
    except (ValueError,KeyError,TypeError):
        return {**base,'state':'unavailable'}
    return {**base,'state':'ready' if safe else 'empty','items':safe,'commands':key in ('verification','moderation')}


@router.get('/queues')
async def queues(request:Request,p=Depends(principal)):
    return {'queues':[await read_queue(key,request,p) for key in QUEUES]}


@router.get('/queues/{key}')
async def detail(key:str,request:Request,p=Depends(principal)):
    if key not in QUEUES:
        raise HTTPException(404)
    require_scope(p,QUEUES[key]['permission'])
    return await read_queue(key,request,p)


async def run(app,stop):
    upstream=clients(app)
    try:
        await stop.wait()
    finally:
        for client in upstream.values():
            await client.aclose()
