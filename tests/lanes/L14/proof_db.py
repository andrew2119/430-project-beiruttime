"""Explicitly disposable restricted DBs for this lane's loopback browser proof.

Run inside the selected domain image so its complete actual migrations apply.
No ordinary service database or shared container is changed.
"""
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse
from uuid import uuid4
import asyncpg
from bt_runtime.app.db import migrate


async def main():
    action, service, directory = sys.argv[1:]
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    file = root / ('db-' + service + '.json')
    admin_url = os.environ['TEST_DATABASE_ADMIN_URL']
    parsed = urlparse(admin_url)
    if parsed.hostname != 'postgres' or parsed.path != '/postgres':
        raise RuntimeError('Proof admin must be the local maintenance database')
    admin = await asyncpg.connect(admin_url)
    try:
        if action == 'create':
            name = 'bt_l14_' + uuid4().hex
            owner, runtime = name + '_owner', name
            owner_password, runtime_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
            def url(role, password):
                return urlunparse(parsed._replace(netloc=f'{role}:{quote(password)}@postgres:5432', path='/' + name))
            for role, password in [(owner, owner_password), (runtime, runtime_password)]:
                await admin.execute(await admin.fetchval("SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE',$1::text,$2::text)", role, password))
            await admin.execute(f'CREATE DATABASE "{name}" OWNER "{owner}"')
            setup = await asyncpg.connect(urlunparse(parsed._replace(path='/' + name)))
            try:
                await setup.execute(f'''REVOKE ALL ON DATABASE "{name}" FROM PUBLIC;
                    GRANT CONNECT ON DATABASE "{name}" TO "{runtime}";
                    REVOKE ALL ON SCHEMA public FROM PUBLIC; ALTER SCHEMA public OWNER TO "{owner}";
                    GRANT USAGE ON SCHEMA public TO "{runtime}";
                    ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO "{runtime}";
                    ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO "{runtime}";''')
            finally:
                await setup.close()
            state = {'name': name, 'owner': owner, 'runtime': runtime, 'owner_url': url(owner, owner_password), 'runtime_url': url(runtime, runtime_password)}
            file.write_text(json.dumps(state))
            file.chmod(0o600)
            await migrate(state['owner_url'])
        elif action == 'clean':
            state = json.loads(file.read_text())
            if not state['name'].startswith('bt_l14_') or len(state['name']) != 39:
                raise RuntimeError('Not a generated L14 proof database')
            await admin.execute(f'DROP DATABASE "{state["name"]}" WITH (FORCE)')
            for role in [state['runtime'], state['owner']]:
                await admin.execute(f'DROP ROLE "{role}"')
            file.unlink()
        else:
            raise RuntimeError('Use create or clean')
    finally:
        await admin.close()


if __name__ == '__main__':
    asyncio.run(main())
