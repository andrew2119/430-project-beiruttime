"""Disposable service-local databases for the explicit browser contract proof."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import secrets
from urllib.parse import quote, urlparse, urlunparse
from uuid import uuid4
import asyncpg
from bt_runtime.app.db import migrate


@dataclass(frozen=True)
class ProofDatabase:
    runtime_url:str


@asynccontextmanager
async def database(admin_url:str,modules:Path):
    parsed=urlparse(admin_url)
    if parsed.hostname not in ('postgres','localhost','127.0.0.1') or parsed.path!='/postgres':
        raise RuntimeError('Proof databases require the local maintenance database')
    name='bt_test_l09_'+uuid4().hex
    owner,runtime=name+'_owner',name
    owner_password,runtime_password=secrets.token_urlsafe(24),secrets.token_urlsafe(24)
    def url(role,password):
        return urlunparse((parsed.scheme,f'{role}:{quote(password)}@{parsed.hostname}:{parsed.port or 5432}','/'+name,'',parsed.query,''))
    admin=await asyncpg.connect(admin_url)
    created=False
    try:
        for role,password in ((owner,owner_password),(runtime,runtime_password)):
            await admin.execute(await admin.fetchval("SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE',$1::text,$2::text)",role,password))
        await admin.execute(f'CREATE DATABASE "{name}" OWNER "{owner}"')
        created=True
        setup=await asyncpg.connect(urlunparse(parsed._replace(path='/'+name)))
        try:
            await setup.execute(f'''REVOKE ALL ON DATABASE "{name}" FROM PUBLIC;
                GRANT CONNECT ON DATABASE "{name}" TO "{runtime}";
                REVOKE ALL ON SCHEMA public FROM PUBLIC;
                ALTER SCHEMA public OWNER TO "{owner}";
                GRANT USAGE ON SCHEMA public TO "{runtime}";
                ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO "{runtime}";
                ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO "{runtime}";''')
        finally:
            await setup.close()
        await migrate(url(owner,owner_password),modules)
        yield ProofDatabase(url(runtime,runtime_password))
    finally:
        if created:
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        for role in (runtime,owner):
            await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()
