"""Pytest plugin: isolated database AND restricted roles, never a domain schema."""
import os
import secrets
from dataclasses import dataclass
from uuid import uuid4
from urllib.parse import quote, urlparse, urlunparse
import asyncpg
import pytest
import pytest_asyncio
from .app.db import migrate

os.environ['BT_DATABASE_URL'] = 'postgresql://unused/unused'


@dataclass(frozen=True)
class DatabaseAccess:
    owner_url: str
    runtime_url: str


@pytest_asyncio.fixture
async def database_access(request, tmp_path):
    mode = getattr(request, 'param', 'service')
    if mode not in {'service', 'core-only'}:
        raise ValueError('database_access supports service or core-only migration inventory')
    modules_path = None
    if mode == 'core-only':
        modules_path = tmp_path / 'empty-service-modules'
        modules_path.mkdir()
    admin_url = os.environ.get('TEST_DATABASE_ADMIN_URL')
    if not admin_url:
        pytest.skip('TEST_DATABASE_ADMIN_URL is required for isolated PostgreSQL proofs')
    parsed = urlparse(admin_url)
    if parsed.hostname not in {'postgres', 'localhost', '127.0.0.1'} or parsed.path != '/postgres':
        raise RuntimeError('Test admin must target the local PostgreSQL maintenance database')
    name = 'bt_test_' + uuid4().hex
    owner, runtime = name + '_owner', name
    owner_password, runtime_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    def url(role, password):
        return urlunparse((parsed.scheme, f'{role}:{quote(password)}@{parsed.hostname}:{parsed.port or 5432}',
                           '/' + name, '', parsed.query, ''))
    admin = await asyncpg.connect(admin_url)
    created = False
    try:
        async with admin.transaction():
            # Role/database identifiers are generated hex; passwords are parameter-quoted via format.
            await admin.execute(await admin.fetchval("SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', $1::text,$2::text)", owner, owner_password))
            await admin.execute(await admin.fetchval("SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', $1::text,$2::text)", runtime, runtime_password))
        await admin.execute(f'CREATE DATABASE "{name}" OWNER "{owner}"')
        created = True
        setup = await asyncpg.connect(urlunparse(parsed._replace(path='/' + name)))
        try:
            await setup.execute(f'''REVOKE ALL ON DATABASE "{name}" FROM PUBLIC;
                GRANT CONNECT ON DATABASE "{name}" TO "{runtime}";
                REVOKE ALL ON SCHEMA public FROM PUBLIC;
                ALTER SCHEMA public OWNER TO "{owner}";
                GRANT USAGE ON SCHEMA public TO "{runtime}";
                ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public
                  GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO "{runtime}";
                ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public
                  GRANT USAGE,SELECT ON SEQUENCES TO "{runtime}";''')
        finally:
            await setup.close()
        access = DatabaseAccess(url(owner,owner_password),url(runtime,runtime_password))
        await migrate(access.owner_url, modules_path)
        yield access
    finally:
        if created:
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.execute(f'DROP ROLE IF EXISTS "{runtime}"')
        await admin.execute(f'DROP ROLE IF EXISTS "{owner}"')
        await admin.close()


@pytest_asyncio.fixture
async def database_url(database_access):
    return database_access.runtime_url


@pytest_asyncio.fixture
async def database_owner_url(database_access):
    return database_access.owner_url


@pytest_asyncio.fixture
async def database_runtime_url(database_access):
    return database_access.runtime_url
