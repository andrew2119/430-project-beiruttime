from uuid import UUID,uuid4
import asyncpg
import pytest
from bt_contracts_core.errors import AccessDenied
from bt_runtime.principal import CurrentPrincipal,require_scope
from test_accounts import register,auth,environment as environment,keys as keys


@pytest.mark.asyncio
async def test_organization_grants_stay_scoped_and_fingerprints_are_stable(environment):
    app,client=environment
    session=await register(client)
    subject=UUID(session['account']['id']);first,second=uuid4(),uuid4()
    async with app.state.pool.acquire() as tx:
        await tx.execute('''INSERT INTO identity_access_grants(id,subject_id,organization_id,role,permissions)
            VALUES($1,$2,$3,'dealer',ARRAY['business.jobs.write']),($4,$2,$5,'brand',ARRAY['business.stock.write'])''',uuid4(),subject,second,uuid4(),first)
    refreshed=(await client.post('/v1/accounts/refresh')).json()
    again=(await client.post('/v1/accounts/refresh')).json()
    assert refreshed['access_fingerprint']==again['access_fingerprint']
    assert refreshed['principal']['permissions']==[]
    selected=await client.get('/internal/v1/principal',headers={**auth(session),'X-Actor-ID':str(uuid4())},params={'organization_id':str(first)})
    assert selected.status_code==200
    principal=CurrentPrincipal.model_validate(selected.json())
    assert principal.actor.subject_id==subject and principal.actor.organization_id==first
    require_scope(principal,'business.stock.write',first)
    with pytest.raises(AccessDenied):
        require_scope(principal,'business.jobs.write',first)
    async with app.state.pool.acquire() as tx:
        await tx.execute('UPDATE identity_access_grants SET revoked_at=now() WHERE subject_id=$1 AND organization_id=$2',subject,first)
    assert (await client.get('/internal/v1/principal',headers=auth(session),params={'organization_id':str(first)})).status_code==403


@pytest.mark.asyncio
async def test_application_outbox_failure_rolls_back_case_bytes_and_receipt(environment,database_owner_url):
    app,client=environment
    session=await register(client)
    owner=await asyncpg.connect(database_owner_url)
    async with app.state.pool.acquire() as tx:
        runtime=await tx.fetchval('SELECT current_user')
    try:
        await owner.execute(await owner.fetchval('SELECT format(\'REVOKE INSERT ON outbox FROM %I\',$1::text)',runtime))
        body={'identity_name':'DEMO Seller','contact':'demo@example.test','payout_reference':'DEMO-RECIPIENT','identity_evidence':'DEMO: identity','possession_evidence':'DEMO: possession','expected_revision':0}
        response=await client.post('/v1/private-seller/applications',headers={**auth(session),'Idempotency-Key':'outbox-failure-operation'},json=body)
        assert response.status_code==500
        assert response.json()['error']['code']=='internal_error'
        async with app.state.pool.acquire() as tx:
            for table in ['identity_private_applications','identity_private_evidence','identity_private_operations']:
                assert await tx.fetchval('SELECT count(*) FROM '+table)==0
    finally:
        await owner.execute(await owner.fetchval('SELECT format(\'GRANT INSERT ON outbox TO %I\',$1::text)',runtime))
        await owner.close()
