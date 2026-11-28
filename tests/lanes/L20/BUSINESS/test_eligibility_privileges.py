"""An initial operator can delegate narrowly scoped case assignment authority."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from bt_runtime.app.db import create_pool, unit_of_work
from bt_runtime.app.settings import Settings
from service_app.bootstrap_operator import PERMISSIONS, bootstrap
from service_app.main import create_app


def test_privilege_reason_length_is_checked_after_trimming():
    app = create_app(Settings(database_url='postgresql://unused/unused', service_name='identity'))
    membership = next(module for module in app.state.modules if module.id == 'L02.membership')
    privilege = membership.load('routes.py:EligibilityPrivilege')
    fields = dict(operation_id=uuid4(), subject_id=uuid4(), permission='eligibility.identity.assign')

    with pytest.raises(ValidationError):
        privilege(**fields, reason='     short     ')
    assert privilege(**fields, reason='  Valid reason  ').reason == 'Valid reason'


@pytest.mark.asyncio
@pytest.mark.parametrize(('permission', 'audit_action'), [
    ('eligibility.identity.assign', 'eligibility.privilege'),
    ('identity.private-seller.review', 'private-seller.review.privilege'),
    ('identity.data-requests.restore', 'data-request.restore.privilege'),
    ('identity.data-requests.oversight', 'data-request.oversight.privilege'),
])
async def test_initial_operator_delegates_and_revokes_individual_privilege(database_url, permission, audit_action):
    pool = await create_pool(database_url)
    actor, session, recipient = uuid4(), uuid4(), uuid4()
    bundled_review = permission == 'identity.private-seller.review'
    photo, reader_session, other_scope = uuid4(), uuid4(), uuid4()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    settings = Settings(database_url=database_url, service_name='identity', auth_public_key=public.decode())
    app = create_app(settings)
    app.state.pool = pool
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=5)
    try:
        async with unit_of_work(pool) as tx:
            for account, email in [(actor, 'test-operator@example.invalid'), (recipient, 'test-assignee@example.invalid')]:
                await tx.execute("""INSERT INTO identity_accounts(id,email,display_name,password_hash)
                    VALUES($1,$2,'Test person','test-password-hash')""", account, email)
            await tx.execute('INSERT INTO identity_sessions(id,subject_id,expires_at) VALUES($1,$2,$3)',
                             session, actor, expiry)
        if bundled_review:
            await bootstrap(pool, 'test-assignee@example.invalid', 'Authorize the first operator')
            async with unit_of_work(pool) as tx:
                await tx.execute("""INSERT INTO identity_access_grants(id,subject_id,role,permissions)
                    VALUES(gen_random_uuid(),$1,'test-administrator',ARRAY['identity.membership.manage'])""", actor)
                await tx.execute("""INSERT INTO identity_access_grants(id,subject_id,organization_id,role,permissions)
                    VALUES(gen_random_uuid(),$1,$2,'test-scoped-review',ARRAY[$3::text])""",
                    recipient, other_scope, permission)
                await tx.execute('INSERT INTO identity_sessions(id,subject_id,expires_at) VALUES($1,$2,$3)',
                                 reader_session, recipient, expiry)
                listing = uuid4()
                await tx.execute("""INSERT INTO identity_l19_possession(listing_id,subject_id,proof)
                    VALUES($1,$2,'{}')""", listing, actor)
                await tx.execute("""INSERT INTO identity_l19_possession_photos
                    (id,listing_id,subject_id,challenge_id,content,created_at,submitted_at)
                    VALUES($1,$2,$3,gen_random_uuid(),'test-photo',now(),now())""", photo, listing, actor)
                await tx.execute("""INSERT INTO identity_data_possession_reviews(photo_id,reviewer_id,revision)
                    VALUES($1,$2,1)""", photo, recipient)
        else:
            await bootstrap(pool, 'test-operator@example.invalid', 'Authorize the first operator')
        token = jwt.encode(dict(sub=str(actor), sid=str(session), type='access', iat=now, exp=expiry,
                                iss=settings.auth_issuer, aud=settings.auth_audience), key, algorithm='RS256')
        body = dict(operation_id=str(uuid4()), subject_id=str(recipient), permission=permission,
                    reason='Delegate independent case assignment')
        path = '/v1/memberships/eligibility-privileges'
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test',
                               headers={'Authorization': 'Bearer ' + token}) as client:
            assert (await client.post(path, json={**body, 'business_id': str(uuid4())})).status_code == 422
            assert (await client.post(path, json={**body, 'subject_id': str(actor)})).status_code == 403
            invalid = await client.post(path, json={**body, 'reason': '     short     '})
            assert invalid.status_code == 422
            granted = await client.post(path, json={**body, 'reason': '  ' + body['reason'] + '  '})
            assert granted.status_code == 200
            assert (await client.post(path, json=body)).json() == granted.json()
            assert (await client.post(path, json={**body, 'revoke': True})).status_code == 409
            async with unit_of_work(pool) as tx:
                grant = await tx.fetchrow('''SELECT organization_id,permissions FROM identity_access_grants
                    WHERE id=$1 AND subject_id=$2 AND revoked_at IS NULL''',
                    UUID(granted.json()['grant_id']), recipient)
                assert grant['organization_id'] is None and grant['permissions'] == [permission]
            if bundled_review:
                reader_token = jwt.encode(dict(sub=str(recipient), sid=str(reader_session), type='access',
                                               iat=now, exp=expiry, iss=settings.auth_issuer,
                                               aud=settings.auth_audience), key, algorithm='RS256')
                reader_headers = {'Authorization': 'Bearer ' + reader_token}
                evidence = f'/v1/data-requests/possession-reviews/{photo}/evidence'
                assert (await client.get(evidence, headers=reader_headers)).content == b'test-photo'
            revocation = {**body, 'operation_id': str(uuid4()), 'revoke': True}
            assert (await client.post(path, json={**revocation, 'revoke': 'true'})).status_code == 422
            async with unit_of_work(pool) as tx:
                assert await tx.fetchval('SELECT revoked_at IS NULL FROM identity_access_grants WHERE id=$1',
                                         UUID(granted.json()['grant_id']))
            revoked = await client.post(path, json=revocation)
            assert revoked.status_code == 200
            assert (await client.post(path, json=revocation)).json() == revoked.json()
            if bundled_review:
                assert (await client.get(evidence, headers=reader_headers)).status_code == 403
        async with unit_of_work(pool) as tx:
            assert not await tx.fetchval("""SELECT 1 FROM identity_access_grants
                WHERE subject_id=$1 AND organization_id IS NULL AND revoked_at IS NULL
                AND $2=ANY(permissions)""", recipient, permission)
            if bundled_review:
                grants = await tx.fetch("""SELECT organization_id,permissions FROM identity_access_grants
                    WHERE subject_id=$1 AND revoked_at IS NULL""", recipient)
                assert {grant['organization_id']: grant['permissions'] for grant in grants} == {
                    None: [value for value in PERMISSIONS if value != permission],
                    other_scope: [permission],
                }
            assert await tx.fetchval('SELECT count(*) FROM identity_security_audit WHERE action=$1',
                                     audit_action) == 2
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_business_privileges_require_explicit_grants_in_selected_scope(database_url):
    from bt_contracts_core.errors import AccessDenied
    from bt_runtime.principal import CurrentPrincipal, require_scope

    pool = await create_pool(database_url)
    administrator, member, business, membership, admin_session, member_session = (uuid4() for _ in range(6))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    settings = Settings(database_url=database_url, service_name='identity', auth_public_key=public.decode())
    app = create_app(settings)
    app.state.pool = pool
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=5)

    def headers(subject, session):
        token = jwt.encode(dict(sub=str(subject), sid=str(session), type='access', iat=now, exp=expiry,
                                iss=settings.auth_issuer, aud=settings.auth_audience), key, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token}

    try:
        async with unit_of_work(pool) as tx:
            for subject, session, email in [
                (administrator, admin_session, 'test-scope-admin@example.invalid'),
                (member, member_session, 'test-scope-member@example.invalid'),
            ]:
                await tx.execute("""INSERT INTO identity_accounts(id,email,display_name,password_hash)
                    VALUES($1,$2,'Test person','test-password-hash')""", subject, email)
                await tx.execute('INSERT INTO identity_sessions(id,subject_id,expires_at) VALUES($1,$2,$3)',
                                 session, subject, expiry)
            await tx.execute("""INSERT INTO l02_businesses
                (id,legal_name,public_name,kind,capabilities,assurance_reference,created_by)
                VALUES($1,'Test business','Test business','brand',ARRAY['customization'],'test-assurance',$2)""",
                business, administrator)
            await tx.execute("""INSERT INTO l02_memberships
                (id,business_id,subject_id,capabilities,qualifications,intervention_scope)
                VALUES($1,$2,$3,ARRAY['business.jobs.write'],ARRAY['eligibility.grants.prepare'],'test-scope')""",
                membership, business, member)
            await tx.execute("""INSERT INTO identity_access_grants(id,subject_id,organization_id,role,permissions)
                VALUES(gen_random_uuid(),$1,$2,'brand',ARRAY['business.jobs.write'])""", member, business)
        await bootstrap(pool, 'test-scope-admin@example.invalid', 'Authorize the first operator')
        commands = [dict(operation_id=str(uuid4()), subject_id=str(member), business_id=str(business),
                         permission='eligibility.grants.' + action, reason='Authorize consent under selected business')
                    for action in ('prepare', 'consume', 'revoke')]
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            async def principal(organization=None):
                params = {'organization_id': str(organization)} if organization else {}
                response = await client.get('/internal/v1/principal', params=params, headers=headers(member, member_session))
                assert response.status_code == 200
                return CurrentPrincipal.model_validate(response.json())

            before = await principal(business)
            privilege_path = '/v1/memberships/eligibility-privileges'
            admin_headers = headers(administrator, admin_session)
            receipts = []
            for command in commands:
                with pytest.raises(AccessDenied):
                    require_scope(before, command['permission'], business)
                issued = await client.post(privilege_path, json=command, headers=admin_headers)
                assert issued.status_code == 200
                receipts.append(issued.json())
            selected, unselected = await principal(business), await principal()
            for command in commands:
                require_scope(selected, command['permission'], business)
                with pytest.raises(AccessDenied):
                    require_scope(unselected, command['permission'], business)
            with pytest.raises(AccessDenied):
                require_scope(selected, 'eligibility.identity.review')

            revoked = await client.patch(
                f'/v1/businesses/{business}',
                headers={**admin_headers, 'Idempotency-Key': 'test-revoke-eligibility-business'},
                json={'revision': 1, 'state': 'revoked', 'reason': 'End current business access'},
            )
            assert revoked.status_code == 200, revoked.text
            for command, receipt in zip(commands, receipts):
                replay = await client.post(privilege_path, json=command, headers=admin_headers)
                assert replay.json() == receipt
                denied = await client.post(
                    privilege_path, json={**command, 'operation_id': str(uuid4())}, headers=admin_headers,
                )
                assert denied.status_code == 409
        async with unit_of_work(pool) as tx:
            assert await tx.fetchval("""SELECT count(*) FROM identity_access_grants
                WHERE subject_id=$1 AND organization_id=$2 AND revoked_at IS NULL""", member, business) == 0
            assert await tx.fetchval('SELECT count(*) FROM identity_eligibility_privileges') == len(commands)
    finally:
        await pool.close()
