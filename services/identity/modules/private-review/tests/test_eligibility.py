from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from bt_contracts.catalog.listings.eligibility import PublicationEligibility
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover

pytest_plugins = ["bt_runtime.testing"]
MODULES = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def scenario(database_url):
    app = create_app(Settings(database_url=database_url, service_name='identity',
                              modules_path=MODULES, service_auth_public_key=''))
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives import serialization
    app.state.settings.service_auth_public_key = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    app.state.pool = await db.create_pool(database_url)
    actor, listing, watch, case = uuid4(), uuid4(), uuid4(), uuid4()
    async with app.state.pool.acquire() as tx:
        await tx.execute("INSERT INTO identity_accounts(id,email,display_name,password_hash) VALUES($1,'seller@example.test','Test Seller','test-password-hash')", actor)
        await tx.execute("INSERT INTO identity_private_applications(id,subject_id,revision,status,identity_name,contact,payout_reference) VALUES($1,$2,1,'approved','Test Seller','seller@example.test','DEMO-test')", case, actor)
        await tx.execute("INSERT INTO l02_private_reviews(id,application_id,applicant_id,reviewer_id,application_revision,state) VALUES($1,$2,$3,$4,1,'approved')", uuid4(), case, actor, uuid4())
        await tx.execute("INSERT INTO identity_access_grants(id,subject_id,role,permissions) VALUES($1,$2,'private_seller',ARRAY['identity.listings.publish'])", uuid4(), actor)
    binding = dict(schema_version='listing-eligibility.v1', operation_id='test-publication',
                   subject_id=str(listing), listing_id=str(listing), watch_id=str(watch), actor_id=str(actor),
                   organization_id=None, expected_revision=1, identity_digest='0' * 64)
    now = datetime.now(timezone.utc)
    def headers(subject='catalog', kind='service', audience='identity'):
        token = jwt.encode(dict(sub=subject, type=kind, iss='beirut-time-identity', aud=audience,
                                iat=now, exp=now + timedelta(minutes=5)), private, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token, 'Idempotency-Key': binding['operation_id']}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield app, client, binding, headers
    await app.state.pool.close()


class Review:
    async def validate(self, tx, binding):
        now = datetime.now(timezone.utc)
        return dict(binding, state='eligible', current=True, revision=2, duplicate_review='clear',
                    pending_reason=None, next_actor=None, next_review_at=None,
                    proof_listing_id=binding['listing_id'], proof_watch_id=binding['watch_id'],
                    proof_identity_digest=binding['identity_digest'], proof_revision=2,
                    single_use_code_consumed=True, reviewed=True, code_issued_at=now,
                    proof_submitted_at=now + timedelta(minutes=1))


PATH = '/internal/v1/listing-eligibility/validate'


@pytest.mark.asyncio
async def test_catalog_request_and_current_revocation(scenario):
    app, client, binding, headers = scenario
    app.state.listing_eligibility_review = Review()
    response = await client.post(PATH, json=binding, headers=headers())
    assert response.status_code == 200
    proof = PublicationEligibility.model_validate(response.json())
    assert proof.state == 'eligible' and proof.current and proof.duplicate_review == 'clear'
    assert all(response.json()[k] == v for k, v in binding.items())
    async with app.state.pool.acquire() as tx:
        await tx.execute('UPDATE identity_access_grants SET revoked_at=now()')
    assert (await client.post(PATH, json=binding, headers=headers())).json()['state'] == 'denied'


@pytest.mark.asyncio
async def test_unverified_and_missing_review(scenario):
    app, client, binding, headers = scenario
    response = await client.post(PATH, json=binding, headers=headers())
    pending = PublicationEligibility.model_validate(response.json())
    assert pending.state == 'pending' and pending.next_review_at and pending.pending_reason
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE identity_private_applications SET status='pending'")
    assert (await client.post(PATH, json=binding, headers=headers())).json()['state'] == 'denied'


@pytest.mark.asyncio
async def test_service_authentication(scenario):
    _, client, binding, headers = scenario
    for supplied, status in [({'Idempotency-Key': binding['operation_id']}, 401),
                             (headers(kind='access'), 403), (headers(subject='pricing'), 403),
                             (headers(audience='catalog'), 401)]:
        assert (await client.post(PATH, json=binding, headers=supplied)).status_code == status


@pytest.mark.asyncio
async def test_stale_review_and_operation_binding(scenario):
    app, client, binding, headers = scenario
    class Stale(Review):
        async def validate(self, tx, value):
            result = await super().validate(tx, value)
            result['identity_digest'] = '1' * 64
            return result
    app.state.listing_eligibility_review = Stale()
    assert (await client.post(PATH, json=binding, headers=headers())).json()['state'] == 'pending'
    supplied = headers()
    supplied['Idempotency-Key'] = 'test-other-operation'
    conflict = await client.post(PATH, json=binding, headers=supplied)
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'idempotency_conflict'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['dealer', 'brand'])
async def test_business_authority(scenario, kind):
    app, client, binding, headers = scenario
    from uuid import UUID
    organization, actor = uuid4(), UUID(binding['actor_id'])
    binding['organization_id'] = str(organization)
    app.state.listing_eligibility_review = Review()
    async with app.state.pool.acquire() as tx:
        await tx.execute("INSERT INTO l02_businesses(id,legal_name,public_name,kind,capabilities,assurance_reference,created_by) VALUES($1,'Test business','Test business',$2,ARRAY['sales'],'test-assurance',$3)", organization, kind, actor)
        await tx.execute("INSERT INTO l02_memberships(id,business_id,subject_id,capabilities,intervention_scope) VALUES($1,$2,$3,ARRAY['business.stock.write'],'test-sales')", uuid4(), organization, actor)
        await tx.execute("INSERT INTO identity_access_grants(id,subject_id,organization_id,role,permissions) VALUES($1,$2,$3,$4,ARRAY['business.stock.write'])", uuid4(), actor, organization, kind)
    assert (await client.post(PATH, json=binding, headers=headers())).json()['state'] == 'eligible'
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE l02_memberships SET state='revoked'")
    denied = (await client.post(PATH, json=binding, headers=headers())).json()
    assert denied['state'] == 'denied' and denied['duplicate_review'] == 'denied'


@pytest.mark.asyncio
async def test_service_guard_without_storage():
    from types import SimpleNamespace
    from fastapi import HTTPException
    from starlette.requests import Request
    from cryptography.hazmat.primitives import serialization
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    guard = module.load('eligibility.py:catalog_service')
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(database_url='postgresql://unused/unused', service_auth_public_key=
                        private.public_key().public_bytes(serialization.Encoding.PEM,
                        serialization.PublicFormat.SubjectPublicKeyInfo).decode())
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    now = datetime.now(timezone.utc)
    for subject, kind, audience, expected in [('catalog', 'service', 'identity', None),
                                             ('catalog', 'access', 'identity', 403),
                                             ('pricing', 'service', 'identity', 403),
                                             ('catalog', 'service', 'catalog', 401)]:
        token = jwt.encode(dict(sub=subject, type=kind, aud=audience, iss=settings.auth_issuer,
                                iat=now, exp=now + timedelta(minutes=1)), private, algorithm='RS256')
        request = Request(dict(type='http', app=app, headers=[(b'authorization', ('Bearer ' + token).encode())]))
        if expected:
            with pytest.raises(HTTPException) as error:
                await guard(request)
            assert error.value.status_code == expected
        else:
            await guard(request)
    with pytest.raises(HTTPException) as error:
        await guard(Request(dict(type='http', app=app, headers=[])))
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_persisted_review_and_duplicate_admission(scenario):
    import json
    from dataclasses import asdict
    from uuid import UUID
    app, _, binding, _ = scenario
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    provider = module.load('listing_review.py:ReviewProvider')()
    transitions = module.load('listing_review.py:possession')
    make_facts = module.load('listing_review.py:facts')
    async with app.state.pool.acquire() as tx:
        async with tx.transaction():
            assert (await provider.validate(tx, binding))['state'] == 'pending'
            now = datetime.now(timezone.utc)
            challenge = uuid4()
            facts = make_facts(binding)
            proof = transitions.issue(facts, facts.seller_id, challenge, '123456', now)
            proof = transitions.submit(proof, facts, facts.seller_id, 1, challenge, '123456', uuid4(), now, evidence_owned=True)
            reviewer = uuid4()
            proof = transitions.assign(proof, facts, 2, reviewer, operator_permitted=True, reviewer_qualified=True)
            proof = transitions.decide(proof, facts, reviewer, 3, 1, 'approved', 'Test photo inspected', reviewer_qualified=True)
            await tx.execute('UPDATE l02_listing_reviews SET proof=$2::jsonb WHERE listing_id=$1', UUID(binding['listing_id']), json.dumps(asdict(proof), default=str))
            approved = await provider.validate(tx, binding)
            assert PublicationEligibility.model_validate(approved).state == 'eligible'
            other = dict(binding, listing_id=str(uuid4()))
            other['subject_id'] = other['listing_id']
            assert (await provider.validate(tx, other))['state'] == 'denied'
            changed = dict(binding, identity_digest='1' * 64)
            assert (await provider.validate(tx, changed))['state'] == 'denied'
            assert await tx.fetchval("SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted") >= 3


@pytest.mark.asyncio
async def test_revised_stock_reservations_persist(scenario):
    app, _, binding, _ = scenario
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    provider = module.load('listing_review.py:ReviewProvider')()
    binding = dict(binding, organization_id=str(uuid4()))
    async with app.state.pool.acquire() as tx:
        async with tx.transaction():
            assert (await provider.validate(tx, binding))['state'] == 'eligible'
            revised = dict(binding, identity_digest='1' * 64, watch_id=str(uuid4()))
            assert (await provider.validate(tx, revised))['state'] == 'denied'
            assert (await provider.validate(tx, revised))['state'] == 'eligible'
            for admitted in (binding, revised):
                duplicate = dict(admitted, listing_id=str(uuid4()))
                duplicate['subject_id'] = duplicate['listing_id']
                assert (await provider.validate(tx, duplicate))['state'] == 'denied'


@pytest.mark.asyncio
async def test_distinct_matching_models_use_persisted_clearance(scenario):
    import json
    from uuid import UUID
    app, _, binding, _ = scenario
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    provider = module.load('listing_review.py:ReviewProvider')()
    first = dict(binding, organization_id=str(uuid4()))
    second = dict(first, listing_id=str(uuid4()), watch_id=str(uuid4()))
    second['subject_id'] = second['listing_id']
    async with app.state.pool.acquire() as tx:
        async with tx.transaction():
            assert (await provider.validate(tx, first))['state'] == 'eligible'
            assert (await provider.validate(tx, second))['state'] == 'pending'
            clearance = dict(matches=[first['listing_id']], verdict='distinct')
            await tx.execute('UPDATE l02_listing_reviews SET stock_clearance=$2::jsonb WHERE listing_id=$1',
                             UUID(second['listing_id']), json.dumps(clearance))
            assert (await provider.validate(tx, second))['state'] == 'eligible'
            assert await tx.fetchval('SELECT count(*) FROM l02_listing_stock WHERE identity_digest=$1',
                                     binding['identity_digest']) == 2
            revised = dict(second, expected_revision=2)
            assert (await provider.validate(tx, revised))['state'] == 'denied'
            assert (await provider.validate(tx, revised))['state'] == 'pending'
