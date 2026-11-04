"""Start the prebuilt owning runtime with isolated SQL, then stop only this proof stack.

No image rebuild, ordinary domain migration, shared cleanup or sample authority is used.
Requires TEST_DATABASE_ADMIN_URL, the foundation network and the current runtime image.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

import httpx
from bt_runtime.testing import database_access

ROOT = Path(__file__).resolve().parents[3]


def container_url(url):
    parsed = urlsplit(url)
    credentials = parsed.netloc.rsplit('@', 1)[0]
    return urlunsplit((parsed.scheme, credentials + '@postgres:5432', parsed.path, parsed.query, parsed.fragment))


async def main():
    fixture = database_access.__wrapped__()
    access = await anext(fixture)
    try:
        with TemporaryDirectory(prefix='l11-compose-', dir=ROOT / '.venv') as temporary:
            project = 'bt-l11-proof-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]
            image = os.environ.get('L11_RUNTIME_IMAGE', 'beirut-time/l11-service-operations:proof')
            config = {
                'name': project,
                'networks': {'default': {'external': True, 'name': os.environ.get('L11_SHARED_NETWORK', 'beirut-time_default')}},
                'services': {
                    'migrate': {'image': image, 'command': ['python', '-m', 'service_app.migrate'],
                        'environment': {'BT_SERVICE_NAME': 'service-operations', 'BT_DATABASE_URL': '${L11_PROOF_OWNER_URL}'}},
                    'runtime': {'image': image,
                        'environment': {'BT_SERVICE_NAME': 'service-operations', 'BT_DATABASE_URL': '${L11_PROOF_RUNTIME_URL}'},
                        'depends_on': {'migrate': {'condition': 'service_completed_successfully'}},
                        'ports': ['127.0.0.1::8000'], 'init': True, 'cpus': 0.5, 'mem_limit': '192m',
                        'pids_limit': 100, 'read_only': True, 'tmpfs': ['/tmp'],
                        'security_opt': ['no-new-privileges:true'], 'cap_drop': ['ALL']},
                },
            }
            path = Path(temporary) / 'compose.json'
            path.write_text(json.dumps(config))
            compose = ['docker', 'compose', '-f', str(path)]
            env = {**os.environ, 'L11_PROOF_OWNER_URL': container_url(access.owner_url),
                'L11_PROOF_RUNTIME_URL': container_url(access.runtime_url)}
            active = subprocess.check_output([*compose, 'ps', '--status', 'running', '--quiet'], env=env, text=True)
            if active.strip():
                raise RuntimeError('This worktree already has a running proof; nothing was stopped')
            try:
                subprocess.run([*compose, 'up', '-d', '--wait', '--wait-timeout', '40', '--no-build'], env=env, check=True)
                address = subprocess.check_output([*compose, 'port', 'runtime', '8000'], env=env, text=True).strip()
                async with httpx.AsyncClient(base_url='http://' + address) as client:
                    assert (await client.get('/health/ready')).is_success
                    result = await client.get('/v1/directory/businesses')
                    assert result.status_code == 200 and result.json() == {'items': [], 'next_after': None}
                    assert (await client.get('/v1/directory/choices/current')).status_code == 401
                print(json.dumps({'runtime_ready': True, 'isolated_migrations': True,
                    'directory_route': True, 'private_route_denied_without_session': True}))
            finally:
                subprocess.run([*compose, 'stop'], env=env, check=True)
    finally:
        await fixture.aclose()


if __name__ == '__main__':
    asyncio.run(main())
