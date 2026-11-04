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
from testing_database import disposable_database

ROOT = Path(__file__).resolve().parents[3]


def container_url(url):
    parsed = urlsplit(url)
    credentials = parsed.netloc.rsplit('@', 1)[0]
    return urlunsplit((parsed.scheme, credentials + '@postgres:5432', parsed.path, parsed.query, parsed.fragment))


async def main():
    service = os.environ.get('L11_RUNTIME_SERVICE', 'service-operations')
    if service not in {'service-operations', 'catalog'}:
        raise ValueError('Choose the owning service-operations or catalog runtime')
    async with disposable_database() as access:
        with TemporaryDirectory(prefix='l11-compose-', dir=ROOT / '.venv') as temporary:
            project = 'bt-l11-proof-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8] + ('-catalog' if service == 'catalog' else '')
            image = os.environ.get('L11_RUNTIME_IMAGE', 'beirut-time/l11-service-operations:proof')
            if service == 'catalog' and 'L11_RUNTIME_IMAGE' not in os.environ:
                raise ValueError('Pass the existing Catalog runtime/test image explicitly')
            config = {
                'name': project,
                'networks': {'default': {'external': True, 'name': os.environ.get('L11_SHARED_NETWORK', 'beirut-time_default')}},
                'services': {
                    'migrate': {'image': image, 'command': ['python', '-m', 'service_app.migrate'],
                        'environment': {'BT_SERVICE_NAME': service, 'BT_DATABASE_URL': '${L11_PROOF_OWNER_URL}'}},
                    'runtime': {'image': image,
                        'command': ['uvicorn', 'bt_runtime.app.main:create_app', '--factory', '--host', '0.0.0.0', '--port', '8000', '--no-access-log'],
                        'environment': {'BT_SERVICE_NAME': service, 'BT_DATABASE_URL': '${L11_PROOF_RUNTIME_URL}',
                            'IDENTITY_API_URL': 'http://127.0.0.1:1'},
                        'healthcheck': {'test': ['CMD', 'python', '-c', "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=2)"],
                            'interval': '1s', 'timeout': '3s', 'retries': 20, 'start_period': '1s'},
                        'depends_on': {'migrate': {'condition': 'service_completed_successfully'}},
                        'ports': ['127.0.0.1::8000'], 'init': True, 'cpus': 0.5, 'mem_limit': '192m',
                        'pids_limit': 100, 'read_only': True, 'tmpfs': ['/tmp'],
                        'security_opt': ['no-new-privileges:true'], 'cap_drop': ['ALL']},
                },
            }
            if service == 'catalog':
                mounts = [str(ROOT / 'services/catalog/modules/options/movement') + ':/app/modules/options/movement:ro']
                for entry in config['services'].values():
                    entry['volumes'] = mounts
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
                    if service == 'catalog':
                        result = await client.get('/v1/options/movement?brand_id=00000000-0011-4000-8000-000000000001')
                        assert result.status_code == 503 and result.json()['error']['code'] == 'unavailable'
                        private = '/v1/options/movement/selections/current?brand_id=00000000-0011-4000-8000-000000000001'
                    else:
                        result = await client.get('/v1/directory/businesses')
                        assert result.status_code == 200 and result.json() == {'items': [], 'next_after': None}
                        private = '/v1/directory/choices/current'
                    assert (await client.get(private)).status_code == 401
                print(json.dumps({'runtime_ready': True, 'isolated_migrations': True,
                    'own_domain_route_verified': True, 'private_route_denied_without_session': True}))
            finally:
                subprocess.run([*compose, 'stop'], env=env, check=True)


if __name__ == '__main__':
    asyncio.run(main())
