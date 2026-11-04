import asyncio
import json
from pathlib import Path
from uuid import UUID
import httpx
import pytest
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings

REPORTER=UUID('10000000-0000-4000-8000-000000000001')
SELLER=UUID('10000000-0000-4000-8000-000000000002')
REVIEWER=UUID('10000000-0000-4000-8000-000000000003')
OTHER=UUID('10000000-0000-4000-8000-000000000004')
LISTING=UUID('20000000-0000-4000-8000-000000000001')
MESSAGE=UUID('20000000-0000-4000-8000-000000000002')
MODULES=Path('/app/modules')


@pytest_asyncio.fixture
async def api(database_url,database_owner_url):
    await db.migrate(database_owner_url,MODULES)
    app=create_app(Settings(database_url=database_url,modules_path=MODULES,service_name='trust'))
    app.state.pool=await db.create_pool(database_url)
    def fixture(request):
        if request.url.path=='/internal/v1/principal':
            token=request.headers.get('Authorization','').removeprefix('Bearer ')
            identities={'reporter':REPORTER,'seller':SELLER,'reviewer':REVIEWER,'other':OTHER}
            if token not in identities:
                return httpx.Response(401)
            return httpx.Response(200,json={'actor':{'subject_id':str(identities[token]),'session_id':'fixture-session'},'roles':['operator'] if token in ('seller','reviewer','other') else ['buyer'],
                'permissions':(['moderation.review','moderation.decide']+(['moderation.assign'] if token in ('other','seller') else [])) if token!='reporter' else [],'organizations':[],'organization_grants':[]})
        if request.url.path==f'/v1/accounts/{SELLER}/report-subject':
            return httpx.Response(200,json={'subject_id':str(SELLER)})
        if request.url.path==f'/v1/messages/{MESSAGE}':
            return httpx.Response(200,json={'sender_id':str(SELLER)}) if request.headers.get('Authorization')=='Bearer reporter' else httpx.Response(403)
        if request.url.path==f'/v1/listings/{LISTING}/report-subject':
            return httpx.Response(200,json={'id':str(LISTING),'seller_id':str(SELLER)})
        return httpx.Response(404)
    app.state.moderation_clients={name:DependencyClient(name,'http://fixture',transport=httpx.MockTransport(fixture)) for name in ('identity','catalog','communications')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://trust') as client:
        yield client,app
    for client in app.state.moderation_clients.values():
        await client.aclose()
    await app.state.pool.close()


def headers(actor='reporter',key='report-key-0001',revision=None):
    result={'Authorization':'Bearer '+actor,'Idempotency-Key':key}
    if revision is not None:
        result['If-Match']=str(revision)
    return result


async def report(client,key='report-key-0001'):
    return await client.post('/v1/moderation/reports',headers=headers(key=key),json={'target_kind':'listing','target_id':str(LISTING),'category':'misleading','evidence':'Private condition photo reference and reported issue'})


@pytest.mark.asyncio
async def test_report_claim_hide_reinstate_appeal_and_durable_outbox(api):
    client,app=api
    created=await report(client)
    assert created.status_code==201,created.text
    case=created.json()['id']
    duplicate=await report(client)
    assert duplicate.json()==created.json()
    base=f'/v1/moderation/cases/{case}'
    assert (await client.get(base,headers=headers('other'))).status_code==403
    subject_detail=(await client.get(base,headers=headers('seller'))).json()
    assert 'evidence' not in subject_detail and 'reporter_id' not in subject_detail
    assert (await client.post(base+'/claim',headers=headers('seller','self-claim',1))).status_code==403
    claim=await client.post(base+'/claim',headers=headers('reviewer','claim-key',1))
    assert claim.status_code==200,claim.text
    assert (await client.get(base,headers=headers('other'))).status_code==403
    hidden=await client.post(base+'/decisions',headers=headers('reviewer','hide-key-01',2),json={'action':'hide','reason':'Misleading condition requires correction'})
    assert hidden.status_code==200,hidden.text
    assert hidden.json()['preserve_transaction_duties'] is True
    replay=await client.post(base+'/decisions',headers=headers('reviewer','hide-key-01',2),json={'action':'hide','reason':'Misleading condition requires correction'})
    assert replay.json()==hidden.json()
    changed_revision=await client.post(base+'/decisions',headers=headers('reviewer','hide-key-01',3),json={'action':'hide','reason':'Misleading condition requires correction'})
    assert changed_revision.status_code==409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM moderation_cases')==1
        assert await tx.fetchval('SELECT count(*) FROM outbox')==1
        envelope=json.loads(await tx.fetchval('SELECT envelope FROM outbox'))
        assert 'evidence' not in envelope['data'] and 'reason' not in envelope['data']
        assert envelope['data']['action']=='hide'
    stale=await client.post(base+'/decisions',headers=headers('reviewer','stale-key-1',2),json={'action':'reinstate','reason':'Corrected description'})
    assert stale.status_code==409
    appeal=await client.post(base+'/appeals',headers=headers('reporter','appeal-key',3),json={'reason':'The listing was corrected'})
    assert appeal.json()['status']=='appealed'
    reclaimed=await client.post(base+'/claim',headers=headers('reviewer','reclaim-key',4))
    assert reclaimed.json()['status']=='appealed'
    assert (await client.get(base,headers=headers('reviewer'))).json()['status']=='appealed'
    restored=await client.post(base+'/decisions',headers=headers('reviewer','restore-key',5),json={'action':'reinstate','reason':'Verified the corrected description'})
    assert restored.status_code==200
    detail=(await client.get(base,headers=headers('reviewer'))).json()
    assert detail['revision']==6 and detail['delivery']=='pending'
    assert len(detail['audit'])==5
    # A fresh process/pool sees the acknowledged state; no in-memory domain store.
    other_pool=await db.create_pool(app.state.settings.database_url)
    try:
        async with other_pool.acquire() as tx:
            assert await tx.fetchval('SELECT last_action FROM moderation_cases WHERE id=$1',UUID(case))=='reinstate'
    finally:
        await other_pool.close()


@pytest.mark.asyncio
async def test_permissions_conflicts_scoped_previews_and_atomic_races(api):
    client,app=api
    assert (await client.get('/v1/moderation/cases',headers=headers())).status_code==403
    assert (await client.post('/v1/moderation/reports',json={})).status_code in (401,422)
    results=await asyncio.gather(*(report(client) for _ in range(4)))
    assert len({r.json()['id'] for r in results})==1
    case=results[0].json()['id']
    queue=(await client.get('/v1/moderation/cases',headers=headers('reviewer'))).json()
    assert 'evidence' not in queue['items'][0] and 'reporter_id' not in queue['items'][0]
    assert (await client.get('/v1/moderation/cases',headers=headers('seller'))).json()['items']==[]
    body={'target_kind':'listing','target_id':str(LISTING),'category':'other','evidence':'Different private note'}
    conflict=await client.post('/v1/moderation/reports',headers=headers(),json=body)
    assert conflict.status_code==409
    raced=await asyncio.gather(*(client.post(f'/v1/moderation/cases/{case}/claim',headers=headers(actor,actor+'-claim-key',1)) for actor in ('reviewer','other')))
    assert sorted(r.status_code for r in raced)==[200,409] or sorted(r.status_code for r in raced)==[200,403]
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM moderation_audit')==1


@pytest.mark.asyncio
async def test_assignment_recovery_never_grants_unassigned_evidence_or_self_review(api):
    client,_=api
    case=(await report(client)).json()['id']
    base=f'/v1/moderation/cases/{case}'
    await client.post(base+'/claim',headers=headers('reviewer','recovery-claim',1))
    assert (await client.get(base,headers=headers('other'))).status_code==403
    reason={'reason':'Current reviewer no longer available for this case'}
    assert (await client.post(base+'/release',headers=headers('reviewer','release-no-grant',2),json=reason)).status_code==403
    assert (await client.post(base+'/release',headers=headers('seller','release-self-key',2),json=reason)).status_code==403
    result=await client.post(base+'/release',headers=headers('other','release-key-01',2),json=reason)
    assert result.status_code==200,result.text
    assert result.json()['revision']==3
    assert (await client.get(base,headers=headers('reviewer'))).status_code==403
    queue=(await client.get('/v1/moderation/cases',headers=headers('other'))).json()['items']
    assert queue[0]['can_claim'] is True and queue[0]['can_release'] is False and 'evidence' not in queue[0]
    claimed=await client.post(base+'/claim',headers=headers('other','new-reviewer-claim',3))
    assert claimed.status_code==200
    detail=(await client.get(base,headers=headers('other'))).json()
    assert any(entry['kind']=='release' for entry in detail['audit'])
    replay=await client.post(base+'/release',headers=headers('other','release-key-01',2),json=reason)
    assert replay.json()==result.json()
    denied=await client.post(base+'/decisions',headers=headers('reviewer','old-reviewer-key',4),json={'action':'hide','reason':'No longer assigned'})
    assert denied.status_code==403


@pytest.mark.asyncio
async def test_user_message_targets_and_evidence_scope(api):
    client,_=api
    for kind,target in (('user',SELLER),('message',MESSAGE)):
        result=await client.post('/v1/moderation/reports',headers=headers(key=kind+'-report-key'),json={
            'target_kind':kind,'target_id':str(target),'category':'harassment','evidence':'Private report context'})
        assert result.status_code==201,result.text
    denied=await client.post('/v1/moderation/reports',headers=headers('other','unrelated-message'),json={
        'target_kind':'message','target_id':str(MESSAGE),'category':'harassment','evidence':'Unrelated reader'})
    assert denied.status_code==404
    unknown=await client.post('/v1/moderation/reports',headers=headers(key='unknown-user-key'),json={
        'target_kind':'user','target_id':str(OTHER),'category':'other','evidence':'Unknown user'})
    assert unknown.status_code==404


@pytest.mark.asyncio
async def test_explicit_review_rules_do_not_automatically_penalize_and_rate_is_bounded(api):
    client,app=api
    first=None
    for number in range(10):
        result=await client.post('/v1/moderation/reports',headers=headers(key='velocity-key-'+str(number)),json={
            'target_kind':'listing','target_id':str(LISTING),'category':'payment_abuse','evidence':'Private context '+str(number)})
        assert result.status_code==201
        first=first or result.json()['id']
    limited=await report(client,'eleventh-report-key')
    assert limited.status_code==429
    await client.post(f'/v1/moderation/cases/{first}/claim',headers=headers('reviewer','velocity-claim',1))
    detail=(await client.get(f'/v1/moderation/cases/{first}',headers=headers('reviewer'))).json()
    assert set(detail['review_signals'])=={'duplicate_reports','report_velocity','reported_payment_abuse'}
    assert detail['signals_require_human_review'] is True
    assert detail['last_action'] is None and detail['delivery']=='none'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM outbox')==0
    # Evidence/reasons cannot be whitespace-only, and validation never echoes evidence.
    bad=await client.post('/v1/moderation/reports',headers=headers(key='blank-evidence-key'),json={
        'target_kind':'listing','target_id':str(LISTING),'category':'other','evidence':'   '})
    assert bad.status_code==422


@pytest.mark.asyncio
async def test_expired_subject_lookup_preserves_refresh_status_without_creating_case(api):
    client,app=api
    await app.state.moderation_clients['catalog'].aclose()
    app.state.moderation_clients['catalog']=DependencyClient('catalog','http://fixture',transport=httpx.MockTransport(lambda request:httpx.Response(401)))
    response=await report(client,'expired-subject-key')
    assert response.status_code==401
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM moderation_cases')==0


@pytest.mark.asyncio
async def test_unavailable_identity_or_catalog_cannot_create_report(api):
    client,app=api
    for dependency in ('catalog','identity'):
        old=app.state.moderation_clients[dependency]
        await old.aclose()
        app.state.moderation_clients[dependency]=DependencyClient(dependency,'http://fixture',transport=httpx.MockTransport(lambda request:httpx.Response(503)))
        result=await report(client,dependency+'-down-key')
        assert result.status_code==503
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM moderation_cases')==0
