import asyncio
from uuid import uuid4

import asyncpg
import pytest
from service_app.bootstrap_operator import bootstrap, BootstrapDenied, PERMISSIONS


async def account(pool, email):
    subject = uuid4()
    await pool.execute("INSERT INTO identity_accounts(id,email,display_name,password_hash) VALUES($1,$2,'Sample','not-a-login')", subject, email)
    return subject


@pytest.mark.asyncio
async def test_bootstrap_one_time_atomic_audited_and_current(database_url):
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3)
    try:
        a = await account(pool, 'first@example.test')
        await account(pool, 'second@example.test')
        results = await asyncio.gather(bootstrap(pool, ' FIRST@example.test ', 'Initial local operator authorization'), bootstrap(pool, 'second@example.test', 'Competing initial operator authorization'), return_exceptions=True)
        assert sum(isinstance(r, str) for r in results) == 1
        assert sum(isinstance(r, BootstrapDenied) for r in results) == 1
        grant = await pool.fetchrow('SELECT * FROM identity_access_grants')
        assert set(grant['permissions']) == set(PERMISSIONS)
        assert grant['organization_id'] is None and grant['role'] == 'operator'
        assert await pool.fetchval('SELECT count(*) FROM identity_operator_bootstrap') == 1
        assert await pool.fetchval("SELECT count(*) FROM identity_security_audit WHERE action='operator.bootstrap' AND outcome='accepted'") == 1
        assert await pool.fetchval('SELECT access_revision FROM identity_accounts WHERE id=$1', grant['subject_id']) == 2
        await pool.execute('UPDATE identity_access_grants SET revoked_at=now()')
        with pytest.raises(BootstrapDenied):
            await bootstrap(pool, 'first@example.test', 'Must not reopen revoked access')
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_bootstrap_rejects_missing_suspended_and_existing_operator(database_url):
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=1)
    try:
        with pytest.raises(BootstrapDenied):
            await bootstrap(pool, 'absent@example.test', 'Initial authorization attempt')
        subject = await account(pool, 'first@example.test')
        await pool.execute("UPDATE identity_accounts SET status='suspended'")
        with pytest.raises(BootstrapDenied):
            await bootstrap(pool, 'first@example.test', 'Suspended authorization attempt')
        await pool.execute("UPDATE identity_accounts SET status='active'")
        with pytest.raises(BootstrapDenied):
            await bootstrap(pool, 'first@example.test', 'short')
        await pool.execute("INSERT INTO identity_access_grants(id,subject_id,role,permissions,revoked_at) VALUES($1,$2,'operator','{}',now())", uuid4(), subject)
        with pytest.raises(BootstrapDenied):
            await bootstrap(pool, 'first@example.test', 'Existing operator must not allow rebootstrap')
        assert await pool.fetchval('SELECT count(*) FROM identity_operator_bootstrap') == 0
        assert await pool.fetchval('SELECT count(*) FROM identity_security_audit') == 0
    finally:
        await pool.close()
