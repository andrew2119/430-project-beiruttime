from uuid import UUID,uuid4
import pytest
from test_consent import payload,environment as environment,keys as keys


@pytest.mark.asyncio
async def test_assigned_current_reviewer_and_withdrawal_deny_bytes(environment):
    app,client,state=environment
    record=(await client.post('/v1/consents',headers={'Idempotency-Key':'evidence-case'},json=payload(state))).json()['consent']
    identifier=UUID(record['id']);reviewer=uuid4()
    async with app.state.pool.acquire() as tx:
        proof=await tx.fetchval('SELECT id FROM eligibility_consent_evidence WHERE consent_id=$1',identifier)
    path=f'/v1/consents/{identifier}/evidence/{proof}'
    reviewer_auth={'Authorization':'Bearer '+state['token'](reviewer)}
    state['permissions']=['eligibility.identity.review']
    # Authority without assignment, and self-review, are both denied.
    assert (await client.get(path,headers=reviewer_auth)).status_code==403
    async with app.state.pool.acquire() as tx:
        await tx.execute('INSERT INTO eligibility_consent_assignments(consent_id,reviewer_id) VALUES($1,$2),($1,$3)',identifier,reviewer,state['buyer'])
    assert (await client.get(path)).status_code==403
    assert (await client.get(path,headers=reviewer_auth)).text.startswith('DEMO:')
    state['permissions']=[]
    assert (await client.get(path,headers=reviewer_auth)).status_code==403
    state['permissions']=['eligibility.identity.review']
    assert (await client.post(f'/v1/consents/{identifier}/withdraw',headers={'Idempotency-Key':'withdraw-evidence'},json={'expected_revision':1})).status_code==200
    assert (await client.get(path,headers=reviewer_auth)).status_code==403


@pytest.mark.asyncio
async def test_utf8_byte_bound_and_policy_rejection_are_atomic(environment):
    app,client,state=environment
    oversized='DEMO:'+'أ'*32767
    response=await client.post('/v1/consents',headers={'Idempotency-Key':'utf8-byte-limit'},json=payload(state,evidence=oversized))
    assert response.status_code==422
    refusal_with_bytes=await client.post('/v1/consents',headers={'Idempotency-Key':'refusal-with-bytes'},json=payload(state,decision='refuse'))
    assert refusal_with_bytes.status_code==422
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM eligibility_consents')==0
        assert await tx.fetchval('SELECT count(*) FROM eligibility_consent_evidence')==0
        assert await tx.fetchval('SELECT count(*) FROM outbox')==0
