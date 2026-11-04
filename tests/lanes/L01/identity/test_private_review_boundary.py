from uuid import UUID,uuid4
import pytest
from test_accounts import register,auth,environment as environment,keys as keys


@pytest.mark.asyncio
async def test_assigned_reviewer_only_and_current_permission(environment):
    app,client=environment
    owner=await register(client)
    payload={'identity_name':'DEMO Seller','contact':'demo@example.test','payout_reference':'DEMO-RECIPIENT','identity_evidence':'DEMO: identity','possession_evidence':'DEMO: possession','expected_revision':0}
    case=(await client.post('/v1/private-seller/applications',headers={**auth(owner),'Idempotency-Key':'case-operation'},json=payload)).json()['application']
    reviewer=await register(client,'reviewer@example.test','register-reviewer')
    reviewer_id=UUID(reviewer['account']['id']);case_id=UUID(case['id']);grant_id=uuid4()
    async with app.state.pool.acquire() as tx:
        proof_id=await tx.fetchval('SELECT id FROM identity_private_evidence WHERE application_id=$1 LIMIT 1',case_id)
        await tx.execute("INSERT INTO identity_access_grants(id,subject_id,role,permissions) VALUES($1,$2,'operator',ARRAY['identity.private-seller.review'])",grant_id,reviewer_id)
    path=f'/v1/private-seller/applications/{case_id}/evidence/{proof_id}'
    assert (await client.get(path,headers=auth(reviewer))).status_code==403
    async with app.state.pool.acquire() as tx:
        await tx.execute('INSERT INTO identity_private_assignments(application_id,reviewer_id) VALUES($1,$2)',case_id,reviewer_id)
    assert (await client.get(path,headers=auth(reviewer))).text.startswith('DEMO:')
    async with app.state.pool.acquire() as tx:
        await tx.execute('UPDATE identity_access_grants SET revoked_at=now() WHERE id=$1',grant_id)
    assert (await client.get(path,headers=auth(reviewer))).status_code==403
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE identity_private_applications SET status='correction',revision=revision+1,reason='Use synthetic possession proof' WHERE id=$1",case_id)
    assert (await client.post('/v1/private-seller/applications',headers={**auth(owner),'Idempotency-Key':'stale-correction'},json=payload)).status_code==409
    corrected=await client.post('/v1/private-seller/applications',headers={**auth(owner),'Idempotency-Key':'valid-correction'},json={**payload,'expected_revision':2})
    assert corrected.status_code==200 and corrected.json()['application']['revision']==3
