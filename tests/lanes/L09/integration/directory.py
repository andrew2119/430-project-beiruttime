"""Real Directory/Intake composition; only Identity transport is an explicit V1 fixture."""
from pathlib import Path
from uuid import UUID
import httpx
import pytest
from bt_bulkheads import DependencyClient
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings

ORG='30000000-0000-4000-8000-000000000001'
ACTOR='30000000-0000-4000-8000-000000000003'
ORDER='30000000-0000-4000-8000-000000000004'
HEADERS={'Authorization':'Bearer contract-staff','Idempotency-Key':'directory-integration-v1'}


@pytest.mark.asyncio
async def test_published_directory_fresh_eligibility_gates_real_intake(database_url,database_owner_url):
    modules=Path('/app/modules')
    assert (modules/'directory/module.json').exists(),'Copy the published Directory V1 provider snapshot first'
    await db.migrate(database_owner_url,modules)
    app=create_app(Settings(database_url=database_url,modules_path=modules,service_name='service-operations'))
    app.state.pool=await db.create_pool(database_url)
    control={'state':'active','capabilities':['servicing']}
    def identity(request):
        if request.url.path=='/internal/v1/principal':
            return httpx.Response(200,json={'actor':{'subject_id':ACTOR,'organization_id':ORG,'session_id':'fixture'},
                'roles':['dealer'],'permissions':[],'organizations':[ORG],
                'organization_grants':[{'organization_id':ORG,'roles':['dealer'],'permissions':['business.records.read','business.jobs.write']}]})
        if request.url.path=='/v1/businesses/'+ORG:
            return httpx.Response(200,json={'id':ORG,'public_name':'SAMPLE CONTRACT DEALER','kind':'dealer',
                'capabilities':control['capabilities'],'state':control['state'],'revision':1,'sample':True,
                'platform_onboarded':True,'authenticated_business':True,'independent_watch_authentication_required':False})
        return httpx.Response(404)
    authority=DependencyClient('identity','http://identity-fixture',transport=httpx.MockTransport(identity))
    directory=DependencyClient('service-operations','http://actual-directory',transport=httpx.ASGITransport(app=app))
    absent=DependencyClient('orders','http://absent-receipts',transport=httpx.MockTransport(lambda request:httpx.Response(404)))
    app.state.l11_identity=authority
    app.state.intake_clients={'identity':authority,'service-operations':directory,'orders':absent,'communications':absent}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://intake') as client:
            path='/v1/intake/records?organization_id='+ORG
            # Official onboarding alone is not a published servicing profile.
            assert (await client.get(path,headers=HEADERS)).status_code==403
            published=await client.put('/v1/directory/businesses/'+ORG,headers=HEADERS,json={
                'expected_revision':0,'capabilities':['maintenance'],'contact':'sample@example.invalid',
                'visit_en':'Sample visits by arrangement','visit_ar':'زيارات تجريبية بترتيب مسبق',
                'scope_en':'Sample assessment only; no custody or work pass','scope_ar':'تقييم تجريبي فقط دون استلام أو نتيجة عمل','published':True})
            assert published.status_code==200,published.text
            proof=await client.get('/v1/directory/providers/'+ORG)
            assert proof.json()=={'organization_id':ORG,'official':True,'active':True,'kind':'dealer'}
            created=await client.post(path,headers={**HEADERS,'Idempotency-Key':'intake-integration-v1'},json={
                'order_id':ORDER,'custody_receipt_id':None,'serial':'SAMPLE-PRIVATE-INTEGRATION','reference':'SAMPLE-REF',
                'movement':'SAMPLE automatic','received_condition':'SAMPLE reported scratch','accessories':'SAMPLE box',
                'reported_issue':'SAMPLE assessment requested','assessed_issue':'SAMPLE not assessed',
                'diagnostic_opening_permission':False,'no_polish_acknowledged':False,'fee_acknowledged':False,
                'fee_minor':0,'currency':'USD'})
            assert created.status_code==201,created.text
            assert created.json()['state']=='awaiting_intake' and created.json()['diagnosis_allowed'] is False
            private='/v1/intake/records/'+created.json()['id']+'?organization_id='+ORG
            assert (await client.get(private,headers=HEADERS)).status_code==200
            # The real Directory adapter rechecks current Identity on each intake read.
            for state,capabilities in (('revoked',['servicing']),('active',['sales'])):
                control.update(state=state,capabilities=capabilities)
                denied=await client.get(private,headers=HEADERS)
                assert denied.status_code==403,denied.text
                assert 'SAMPLE-PRIVATE-INTEGRATION' not in denied.text
            control.update(state='active',capabilities=['servicing'])
            assert (await client.get(private,headers=HEADERS)).status_code==200
            async with app.state.pool.acquire() as tx:
                assert await tx.fetchval('SELECT count(*) FROM directory_profiles WHERE organization_id=$1',UUID(ORG))==1
                assert await tx.fetchval('SELECT count(*) FROM technical_intakes')==1
                assert await tx.fetchval('SELECT count(*) FROM outbox')==3
    finally:
        await directory.aclose()
        await absent.aclose()
        await authority.aclose()
        await app.state.pool.close()
