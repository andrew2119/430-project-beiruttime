from pathlib import Path
from uuid import uuid4
import httpx
import pytest
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings


@pytest_asyncio.fixture
async def api():
    app=create_app(Settings(database_url='postgresql://unused',modules_path=Path('/app/modules'),service_name='communications'))
    control={'down':False}
    def fixture(request):
        token=request.headers.get('Authorization','').removeprefix('Bearer ')
        if request.url.path=='/internal/v1/principal':
            if control.get('identity_status'):
                return httpx.Response(control['identity_status'])
            return httpx.Response(200,json={'actor':{'subject_id':str(uuid4()),'session_id':'fixture'},'roles':['buyer'] if token=='buyer' else ['operator'],
                'permissions':[] if token=='unassigned' else ['identity.private-seller.review','moderation.review','authentication.review','disputes.review','quality.review'],
                'organizations':[],'organization_grants':[]})
        if control.get('queue_status'):
            return httpx.Response(control['queue_status'])
        if control['down']:
            return httpx.Response(503)
        state={'state':'assigned'} if request.url.path=='/v1/private-reviews' else {'status':'open'}
        return httpx.Response(200,json={'items':[{'id':str(uuid4()),**state,'revision':1,'evidence':'PRIVATE','identity_document':'PRIVATE'}]})
    app.state.operator_workspace_clients={name:DependencyClient(name,'http://fixture',transport=httpx.MockTransport(fixture)) for name in ('identity','trust')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://communications') as client:
        yield client,control
    for client in app.state.operator_workspace_clients.values():
        await client.aclose()


@pytest.mark.asyncio
async def test_authorized_live_queues_and_honest_prerequisite_states(api):
    client,control=api
    response=await client.get('/v1/operator-workspace/queues',headers={'Authorization':'Bearer operator'})
    assert response.status_code==200,response.text
    queues={row['id']:row for row in response.json()['queues']}
    assert queues['moderation']['state']=='ready'
    assert queues['verification']['items'][0]['status']=='assigned'
    assert 'PRIVATE' not in response.text
    for key in ('inspection','disputes','quality'):
        result=await client.get('/v1/operator-workspace/queues/'+key,headers={'Authorization':'Bearer operator'})
        assert result.status_code==200
        assert result.json()['state']=='awaiting_prerequisite' and result.json()['items']==[] and result.json()['commands'] is False
    control['down']=True
    result=await client.get('/v1/operator-workspace/queues/moderation',headers={'Authorization':'Bearer operator'})
    assert result.json()['state']=='unavailable'


@pytest.mark.asyncio
async def test_identity_and_downstream_queue_expiry_preserve_refresh_status(api):
    client,control=api
    headers={'Authorization':'Bearer operator'}
    control['identity_status']=401
    assert (await client.get('/v1/operator-workspace/queues',headers=headers)).status_code==401
    control['identity_status']=None
    control['queue_status']=401
    assert (await client.get('/v1/operator-workspace/queues',headers=headers)).status_code==401
    control['queue_status']=403
    result=await client.get('/v1/operator-workspace/queues/moderation',headers=headers)
    assert result.status_code==200 and result.json()['state']=='denied'


@pytest.mark.asyncio
async def test_ordinary_or_unassigned_users_never_get_private_queue_previews(api):
    client,_=api
    assert (await client.get('/v1/operator-workspace/queues',headers={'Authorization':'Bearer buyer'})).status_code==403
    assert (await client.get('/v1/operator-workspace/queues/moderation',headers={'Authorization':'Bearer unassigned'})).status_code==403
    result=await client.get('/v1/operator-workspace/queues',headers={'Authorization':'Bearer unassigned'})
    assert all(row['state']=='denied' and row['items']==[] for row in result.json()['queues'])
    assert (await client.get('/v1/operator-workspace/queues')).status_code==401
