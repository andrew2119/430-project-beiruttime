import asyncio
from uuid import UUID, uuid4
import pytest
from L11.conftest import BRAND, DEALER


def headers(token='brand',key='directory-proof-v1'):
    return {'Authorization':'Bearer '+token,'Idempotency-Key':key}


def profile(**changes):
    return {'expected_revision':0,'capabilities':['maintenance','customization'],'contact':'sample@example.invalid',
        'visit_en':'Demo content · visits by arrangement.','visit_ar':'محتوى تجريبي · زيارة بترتيب مسبق.',
        'scope_en':'Sample assessment only.','scope_ar':'تقييم تجريبي فقط.',**changes}


@pytest.mark.asyncio
async def test_only_current_official_businesses_and_brand_destinations(directory):
    client,app,identity = directory
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).status_code==200
    denied = await client.put(f'/v1/directory/businesses/{uuid4()}',json=profile(),headers=headers())
    assert denied.status_code==403
    assert (await client.put(f'/v1/directory/businesses/{DEALER}',json=profile(),headers=headers('dealer'))).status_code==409
    assert (await client.put(f'/v1/directory/businesses/{DEALER}',json=profile(capabilities=['repair']),headers=headers('dealer','dealer-proof-v1'))).status_code==200
    data=(await client.get('/v1/directory/businesses')).json()
    assert len(data['items'])==2 and all(row['sample'] for row in data['items'])
    assert (await client.get(f'/v1/directory/providers/{BRAND}')).json()=={
        'organization_id':str(BRAND),'official':True,'active':True,'kind':'brand'}
    assert len((await client.get('/v1/directory/businesses?purpose=customization')).json()['items'])==1
    identity.status='revoked'
    assert (await client.get('/v1/directory/businesses')).json()['items']==[]
    assert (await client.get(f'/v1/directory/providers/{BRAND}')).status_code==409
    identity.unavailable=True
    unavailable=await client.get('/v1/directory/businesses')
    assert unavailable.status_code==503 and unavailable.json()['error']['code']=='unavailable'


@pytest.mark.asyncio
async def test_publication_scope_revision_replay_and_atomic_outbox(directory):
    client,app,identity=directory
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers('cross'))).status_code==403
    first=await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())
    assert first.status_code==200
    assert any(f'/internal/v1/principal?organization_id={BRAND}' in url for url in identity.requests)
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).json()==first.json()
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(contact='changed'),headers=headers())).status_code==409
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers(key='stale-key-v1'))).status_code==409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM directory_profiles')==1
        assert await tx.fetchval('SELECT count(*) FROM outbox')==1
        assert 'sample@example.invalid' not in await tx.fetchval('SELECT envelope::text FROM outbox LIMIT 1')
    identity.revoked=True
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(expected_revision=1),headers=headers(key='revoked-key-v1'))).status_code==401


@pytest.mark.asyncio
async def test_buyer_choice_private_durable_race_and_no_unsupported_claim(directory):
    client,app,identity=directory
    await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())
    body={'organization_id':str(BRAND),'capability':'maintenance','purpose':'servicing','expected_revision':0,'profile_revision':1}
    assert (await client.post('/v1/directory/choices',json=body)).status_code==401
    responses=await asyncio.gather(*(client.post('/v1/directory/choices',json=body,headers=headers('buyer',f'race-choice-{i}')) for i in range(2)))
    assert sorted(response.status_code for response in responses)==[200,409]
    stored=(await client.get('/v1/directory/choices/current',headers=headers('buyer'))).json()['choice']
    assert stored['revision']==1 and stored['organization_id']==str(BRAND)
    assert (await client.get('/v1/directory/choices/current',headers=headers('other'))).json()['choice'] is None
    assert (await client.post('/v1/directory/choices',json={**body,'expected_revision':1,'capability':'repair'},headers=headers('buyer','unsupported-v1'))).status_code==409
    assert (await client.post('/v1/directory/choices',json={**body,'expected_revision':1,'profile_revision':2},headers=headers('buyer','stale-profile-v1'))).status_code==409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM directory_choices')==1
        assert await tx.fetchval('SELECT count(*) FROM outbox')==2


@pytest.mark.asyncio
async def test_bounds_unknown_fields_and_unonboarded_publication(directory):
    client,app,identity=directory
    identity.onboarded=False
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).status_code==409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM directory_profiles')==0
    assert (await client.get('/v1/directory/businesses?limit=21')).status_code==422
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(extra='forbidden'),headers=headers())).status_code==422
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(expected_revision=True),headers=headers())).status_code==422


@pytest.mark.asyncio
async def test_withdrawal_and_republish_do_not_accept_stale_choices(directory):
    client,app,identity=directory
    await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())
    withdrawn=await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(expected_revision=1,published=False),headers=headers(key='withdraw-profile-v1'))
    assert withdrawn.status_code==200 and withdrawn.json()['revision']==2
    assert (await client.get('/v1/directory/businesses')).json()['items']==[]
    assert (await client.get(f'/v1/directory/businesses/{BRAND}')).status_code==404
    choice={'organization_id':str(BRAND),'capability':'maintenance','purpose':'servicing','expected_revision':0,'profile_revision':1}
    assert (await client.post('/v1/directory/choices',json=choice,headers=headers('buyer','withdrawn-choice-v1'))).status_code==409
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(expected_revision=2),headers=headers(key='republish-profile-v1'))).status_code==200
    assert (await client.post('/v1/directory/choices',json=choice,headers=headers('buyer','old-profile-choice-v1'))).status_code==409
    assert (await client.post('/v1/directory/choices',json={**choice,'profile_revision':3},headers=headers('buyer','current-profile-choice-v1'))).status_code==200


@pytest.mark.asyncio
async def test_service_choice_survives_new_application_and_connection_pool(directory):
    import httpx
    from bt_runtime.app.main import create_app
    from bt_runtime.app.db import create_pool
    client,app,identity=directory
    await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())
    expected=(await client.post('/v1/directory/choices',json={
        'organization_id':str(BRAND),'capability':'customization','purpose':'customization','expected_revision':0,'profile_revision':1},headers=headers('buyer'))).json()
    restarted=create_app(app.state.settings)
    restarted.state.pool=await create_pool(app.state.settings.database_url,1)
    restarted.state.l11_identity=app.state.l11_identity
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),base_url='http://restarted.fixture') as new:
            response=await new.get('/v1/directory/choices/current',headers=headers('buyer'))
            assert response.status_code==200 and response.json()['choice']==expected
    finally:
        await restarted.state.pool.close()


@pytest.mark.asyncio
async def test_servicing_and_customization_scopes_remain_truthful_after_business_change(directory):
    client,app,identity=directory
    await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(capabilities=['customization']),headers=headers())
    assert (await client.get('/v1/directory/businesses?purpose=servicing')).json()['items']==[]
    assert len((await client.get('/v1/directory/businesses?purpose=customization')).json()['items'])==1
    await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(expected_revision=1),headers=headers(key='add-maintenance-v1'))
    identity.kinds[str(BRAND)]='dealer'
    assert (await client.get('/v1/directory/businesses?purpose=customization')).json()['items']==[]
    public=(await client.get(f'/v1/directory/businesses/{BRAND}')).json()
    assert public['kind']=='dealer' and public['capabilities']==['maintenance']
    result=await client.post('/v1/directory/choices',json={
        'organization_id':str(BRAND),'capability':'customization','purpose':'customization','expected_revision':0,'profile_revision':2},headers=headers('buyer'))
    assert result.status_code==409


@pytest.mark.asyncio
async def test_directory_requires_jobs_grant_and_cannot_enlarge_onboarding_scope(directory):
    client,app,identity=directory
    identity.permissions=['business.stock.write']
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).status_code==403
    identity.permissions=['business.jobs.write']
    identity.capabilities[str(BRAND)]=['sales']
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).status_code==409
    identity.capabilities[str(BRAND)]=['servicing','customization']
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).status_code==200
    identity.capabilities[str(BRAND)]=['customization']
    assert (await client.get('/v1/directory/businesses?purpose=servicing')).json()['items']==[]
    assert (await client.get(f'/v1/directory/providers/{BRAND}')).status_code==409
    assert len((await client.get('/v1/directory/businesses?purpose=customization')).json()['items'])==1


@pytest.mark.asyncio
async def test_filtered_scan_stays_bounded_and_keeps_a_progress_cursor(directory):
    client,app,identity=directory
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).status_code==200
    identifiers=[UUID(int=BRAND.int+index) for index in range(21)]
    # Same-module fixture snapshots only; Identity authority remains a separate transport fixture.
    async with app.state.pool.acquire() as tx:
        for organization in identifiers[1:]:
            await tx.execute('''INSERT INTO directory_profiles(organization_id,revision,capabilities,contact,visit_en,visit_ar,scope_en,scope_ar,published)
                SELECT $1,revision,capabilities,contact,visit_en,visit_ar,scope_en,scope_ar,published
                FROM directory_profiles WHERE organization_id=$2''',organization,BRAND)
    for organization in identifiers:
        identity.kinds[str(organization)]='brand'
        identity.capabilities[str(organization)]=['customization']
    identity.capabilities[str(identifiers[-1])]=['servicing']
    identity.requests.clear()
    first=await client.get('/v1/directory/businesses?limit=20')
    assert first.status_code==200
    assert first.json()=={'items':[],'next_after':str(identifiers[19])}
    assert len(identity.requests)==20
    identity.requests.clear()
    second=await client.get('/v1/directory/businesses',params={'after':first.json()['next_after']})
    assert second.status_code==200 and second.json()['next_after'] is None
    assert [item['organization_id'] for item in second.json()['items']]==[str(identifiers[-1])]
    assert len(identity.requests)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('upstream,expected',[(401,401),(403,403),(404,503),(200,503)])
async def test_principal_authentication_scope_and_malformed_responses_stay_distinct(directory,monkeypatch,upstream,expected):
    import httpx
    client,app,identity=directory
    original=identity.handle
    def authority(request):
        if request.url.path=='/internal/v1/principal':
            return httpx.Response(upstream,json={})
        return original(request)
    monkeypatch.setattr(identity,'handle',authority)
    assert (await client.get('/v1/directory/choices/current',headers=headers('buyer'))).status_code==expected
    assert (await client.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).status_code==expected
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM directory_profiles')==0
        assert await tx.fetchval('SELECT count(*) FROM outbox')==0
