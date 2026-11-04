import asyncio
import base64
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone, timedelta
import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError
from bt_bulkheads import DependencyClient
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_contracts.service.intake.v1 import Intake, Receipt

ORG=UUID('30000000-0000-4000-8000-000000000001')
OTHER_ORG=UUID('30000000-0000-4000-8000-000000000002')
ACTOR=UUID('30000000-0000-4000-8000-000000000003')
ORDER=UUID('30000000-0000-4000-8000-000000000004')
RECEIPT=UUID('30000000-0000-4000-8000-000000000005')


@pytest_asyncio.fixture
async def api(database_url,database_owner_url):
    root=Path('/app/modules')
    await db.migrate(database_owner_url,root)
    app=create_app(Settings(database_url=database_url,modules_path=root,service_name='service-operations'))
    app.state.pool=await db.create_pool(database_url)
    control={'receipt_org':ORG,'official':True,'receipt_time':datetime.now(timezone.utc)-timedelta(seconds=1),'orders_down':False,'receipt_fenced':False}
    def fixture(request):
        if request.url.path=='/internal/v1/principal':
            if control.get('identity_status'):
                return httpx.Response(control['identity_status'])
            token=request.headers.get('Authorization','').removeprefix('Bearer ')
            org=OTHER_ORG if token=='other-business' else ORG
            return httpx.Response(200,json={'actor':{'subject_id':str(ACTOR),'organization_id':str(org),'session_id':'fixture'},'roles':['dealer'],'permissions':[],
                'organizations':[str(org)],'organization_grants':[{'organization_id':str(org),'permissions':['business.records.read','business.jobs.write'] if token!='wrong-permission' else [],'roles':['technical_staff']}]})
        if request.url.path.startswith('/v1/directory/providers/'):
            if control.get('directory_status'):
                return httpx.Response(control['directory_status'])
            return httpx.Response(200,json={'organization_id':request.url.path.split('/')[-1],'official':control['official'],'active':True,'kind':'dealer'})
        if request.url.path==f'/v1/custody/receipts/{RECEIPT}':
            if control.get('receipt_status'):
                return httpx.Response(control['receipt_status'])
            if control['orders_down'] or control['receipt_fenced']:
                return httpx.Response(503 if control['orders_down'] else 409)
            return httpx.Response(200,json={'id':str(RECEIPT),'order_id':str(ORDER),'organization_id':str(control['receipt_org']),
                'received_at':control['receipt_time'].isoformat(),'revision':1,'valid':True})
        return httpx.Response(404)
    app.state.intake_clients={name:DependencyClient(name,'http://fixture',transport=httpx.MockTransport(fixture)) for name in ('identity','orders','service-operations','communications')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://intake') as client:
        yield client,app,control
    for client in app.state.intake_clients.values():
        await client.aclose()
    await app.state.pool.close()


def headers(token='staff',key='intake-key-01',revision=None):
    result={'Authorization':'Bearer '+token,'Idempotency-Key':key}
    if revision:
        result['If-Match']=str(revision)
    return result


def body(receipt=None):
    return {'order_id':str(ORDER),'custody_receipt_id':str(receipt) if receipt else None,'serial':'PRIVATE-SERIAL','reference':'REFERENCE','movement':'Automatic',
        'received_condition':'Visible scratch on bezel','accessories':'Box only','reported_issue':'Losing time','assessed_issue':'Assessment not started',
        'diagnostic_opening_permission':False,'no_polish_acknowledged':True,'fee_acknowledged':True,'fee_minor':2500,'currency':'USD'}


@pytest.mark.asyncio
async def test_awaiting_then_actual_custody_permission_restart_and_privacy(api):
    client,app,control=api
    created=await client.post('/v1/intake/records',headers=headers(),json=body())
    assert created.status_code==201,created.text
    assert created.json()['state']=='awaiting_intake' and created.json()['diagnosis_allowed'] is False
    assert (await client.post('/v1/intake/records',headers=headers(),json=body())).json()==created.json()
    record=created.json()['id']
    assert (await client.get('/v1/intake/records/'+record,headers=headers('other-business'))).status_code==404
    assert (await client.get('/v1/intake/records/'+record,headers=headers('wrong-permission'))).status_code==403
    assert (await client.get('/v1/intake/records?organization_id='+str(OTHER_ORG),headers=headers())).status_code==403
    assert (await client.get('/v1/intake/records?organization_id='+str(ORG),headers=headers())).status_code==200
    private=(await client.get('/v1/intake/records/'+record,headers=headers())).json()
    assert private['private_record']['serial']=='PRIVATE-SERIAL'
    queue=(await client.get('/v1/intake/records',headers=headers())).json()
    assert 'serial' not in str(queue)
    received=body(RECEIPT)
    received['diagnostic_opening_permission']=True
    updated=await client.put('/v1/intake/records/'+record,headers=headers(key='receive-key-01',revision=1),json=received)
    assert updated.status_code==200,updated.text
    assert updated.json()['state']=='received' and updated.json()['diagnosis_allowed'] is True
    assert updated.json()['authentication_result'] is None and updated.json()['work_result'] is None
    current=(await client.get('/v1/intake/records/'+record,headers=headers())).json()
    assert current['custody_verification']=='current' and current['diagnosis_allowed'] is True
    control['orders_down']=True
    unavailable=(await client.get('/v1/intake/records/'+record,headers=headers())).json()
    assert unavailable['state']=='received' and unavailable['custody_verification']=='unavailable' and unavailable['diagnosis_allowed'] is False
    control['orders_down']=False
    control['receipt_fenced']=True
    fenced=(await client.get('/v1/intake/records/'+record,headers=headers())).json()
    assert fenced['state']=='received' and fenced['custody_verification']=='unconfirmed' and fenced['diagnosis_allowed'] is False
    control['receipt_fenced']=False
    stale=await client.put('/v1/intake/records/'+record,headers=headers(key='stale-key-01',revision=1),json=received)
    assert stale.status_code==409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM technical_intakes')==1
        assert await tx.fetchval('SELECT count(*) FROM outbox')==4
        events=await tx.fetch('SELECT envelope FROM outbox')
        assert all('PRIVATE-SERIAL' not in event['envelope'] for event in events)
    pool=await db.create_pool(app.state.settings.database_url)
    try:
        async with pool.acquire() as tx:
            assert await tx.fetchval('SELECT state FROM technical_intakes WHERE id=$1',UUID(record))=='received'
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_failed_outbox_intake_rolls_back_private_record_audit_and_request_key(api,monkeypatch):
    client,app,_=api
    module=next(module for module in app.state.modules if module.id=='L09.intake')
    command=module.load('routes.py:save')
    async def failed_enqueue(*args,**kwargs):
        raise RuntimeError('Proof outbox unavailable')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://intake') as guarded:
        with monkeypatch.context() as patch:
            patch.setitem(command.__globals__,'enqueue',failed_enqueue)
            result=await guarded.post('/v1/intake/records',headers=headers(key='rollback-intake'),json=body())
            assert result.status_code==500
    async with app.state.pool.acquire() as tx:
        for table in ('technical_intakes','technical_intake_audit','technical_intake_operations','outbox'):
            assert await tx.fetchval('SELECT count(*) FROM '+table)==0
    retried=await client.post('/v1/intake/records',headers=headers(key='rollback-intake'),json=body())
    assert retried.status_code==201 and retried.json()['revision']==1


@pytest.mark.asyncio
async def test_selected_identity_expiry_and_current_directory_eligibility_denial(api):
    client,_,control=api
    path='/v1/intake/records?organization_id='+str(ORG)
    for upstream,expected in ((401,401),(403,403),(404,503),(503,503)):
        control['identity_status']=upstream
        assert (await client.get(path,headers=headers())).status_code==expected
    control['identity_status']=None
    for upstream,expected in ((401,401),(403,403),(404,403),(409,403),(503,503)):
        control['directory_status']=upstream
        assert (await client.get(path,headers=headers())).status_code==expected


@pytest.mark.asyncio
async def test_wrong_business_future_receipt_official_scope_and_unavailability(api):
    client,app,control=api
    control['receipt_org']=OTHER_ORG
    assert (await client.post('/v1/intake/records',headers=headers(),json=body(RECEIPT))).status_code==409
    control['receipt_org']=ORG
    control['receipt_time']=datetime.now(timezone.utc)+timedelta(seconds=5)
    assert (await client.post('/v1/intake/records',headers=headers(),json=body(RECEIPT))).status_code==409
    control['orders_down']=True
    assert (await client.post('/v1/intake/records',headers=headers(),json=body(RECEIPT))).status_code==503
    control['official']=False
    assert (await client.post('/v1/intake/records',headers=headers(),json=body())).status_code==403
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM technical_intakes')==0


@pytest.mark.asyncio
async def test_receipt_authentication_expiry_cannot_become_custody_or_private_preview(api):
    client,_,control=api
    control['receipt_status']=401
    denied=await client.post('/v1/intake/records',headers=headers(),json=body(RECEIPT))
    assert denied.status_code==401
    control['receipt_status']=None
    created=await client.post('/v1/intake/records',headers=headers(),json=body(RECEIPT))
    assert created.status_code==201
    control['receipt_status']=401
    private=await client.get('/v1/intake/records/'+created.json()['id'],headers=headers())
    assert private.status_code==401 and 'PRIVATE-SERIAL' not in private.text


@pytest.mark.asyncio
async def test_private_photos_and_prior_owner_files_are_scoped_bounded_and_durable(api):
    client,app,_=api
    created=await client.post('/v1/intake/records',headers=headers(),json=body())
    record=created.json()['id']
    png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN3cAAAAASUVORK5CYII='
    upload={'kind':'condition_photo','media_type':'image/png','content_base64':png}
    path=f'/v1/intake/records/{record}/evidence'
    result=await client.post(path,headers=headers(key='private-photo-key',revision=1),json=upload)
    assert result.status_code==201,result.text
    assert (await client.post(path,headers=headers(key='private-photo-key',revision=1),json=upload)).json()==result.json()
    evidence=result.json()['id']
    private_path='/v1/intake/evidence/'+evidence
    assert (await client.get(private_path,headers=headers('other-business'))).status_code==404
    assert (await client.get(private_path,headers=headers('wrong-permission'))).status_code==403
    downloaded=await client.get(private_path,headers=headers())
    assert downloaded.json()['content_base64']==png
    listed=(await client.get(path,headers=headers())).json()['items']
    assert len(listed)==1 and 'content_base64' not in listed[0]
    assert (await client.get(path,headers=headers('other-business'))).status_code==404
    bad={**upload,'content_base64':base64.b64encode(b'<svg>not an image</svg>').decode()}
    assert (await client.post(path,headers=headers(key='bad-image-key',revision=2),json=bad)).status_code==422
    too_large={**upload,'content_base64':base64.b64encode(b'X'*262145).decode()}
    assert (await client.post(path,headers=headers(key='large-image-key',revision=2),json=too_large)).status_code==422
    pdf={'kind':'prior_owner_record','media_type':'application/pdf','content_base64':base64.b64encode(b'%PDF-1.7\nSAMPLE PRIVATE PRIOR RECORD').decode()}
    prior=await client.post(path,headers=headers(key='prior-owner-key',revision=2),json=pdf)
    assert prior.status_code==201
    assert (await client.get('/v1/intake/evidence/'+prior.json()['id'],headers=headers('other-business'))).status_code==404
    detail=(await client.get('/v1/intake/records/'+record,headers=headers())).json()
    assert detail['state']=='awaiting_intake' and detail['revision']==3 and detail['diagnosis_allowed'] is False
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM technical_intake_evidence')==2
        events=await tx.fetch('SELECT envelope FROM outbox')
        assert all('content_base64' not in row['envelope'] and 'PRIVATE PRIOR RECORD' not in row['envelope'] for row in events)


@pytest.mark.asyncio
async def test_receipt_before_equal_after_authoritative_time_boundary(api):
    _,app,_=api
    module=next(module for module in app.state.modules if module.id=='L09.intake')
    matches=module.load('routes.py:receipt_matches')
    now=datetime(2026,11,4,8,0,tzinfo=timezone.utc)
    command=Intake.model_validate(body(RECEIPT))
    for delta,expected in ((-1,True),(0,True),(1,False)):
        receipt=Receipt(id=RECEIPT,order_id=ORDER,organization_id=ORG,received_at=now+timedelta(microseconds=delta),revision=1,valid=True)
        assert matches(receipt,command,ORG,now) is expected


@pytest.mark.parametrize('field,value',[('revision',True),('revision',1.0),('revision','1'),('valid',1),('valid','true'),('valid',False)])
def test_receipt_proof_cannot_coerce_boolean_or_revision(field,value):
    receipt={'id':RECEIPT,'order_id':ORDER,'organization_id':ORG,'received_at':datetime.now(timezone.utc),'revision':1,'valid':True}
    with pytest.raises(ValidationError):
        Receipt.model_validate({**receipt,field:value})


@pytest.mark.asyncio
async def test_integer_money_duplicate_order_and_changed_key_payload(api):
    client,app,control=api
    invalid=body()
    invalid['fee_minor']=1.25
    assert (await client.post('/v1/intake/records',headers=headers(),json=invalid)).status_code==422
    invalid['fee_minor']=True
    assert (await client.post('/v1/intake/records',headers=headers(),json=invalid)).status_code==422
    results=await asyncio.gather(*(client.post('/v1/intake/records',headers=headers(key='race-key-'+str(i)),json=body()) for i in range(2)))
    assert sorted(r.status_code for r in results)==[201,409]
    key='race-key-'+str(next(i for i,r in enumerate(results) if r.status_code==201))
    changed=body()
    changed['serial']='DIFFERENT'
    assert (await client.post('/v1/intake/records',headers=headers(key=key),json=changed)).status_code==409
