"""bt-heavy.sh: real Orders v2.1 provider + isolated Auction component check.

Catalog publication is an explicit frozen read fixture in the test process.
No full three-service or buyer/seller browser acceptance is claimed here.
"""
import json
import os
import secrets
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCAL = ROOT / 'tests/lanes/L14/.local/edit-connected'
PORT = 3633
IMAGES = {'auction': os.environ.get('BT_L14_AUCTION_TEST_IMAGE', 'beirut-time/auction:test-aa853aba-31767'),
    'orders': os.environ.get('BT_L14_ORDERS_IMAGE', 'beirut-time/orders:test-42bf19f1-23729')}


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    LOCAL.chmod(0o700)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', PORT))
    if list(LOCAL.glob('db-*.json')):
        raise RuntimeError('Clean the own prior component proof before creating another database')
    config = json.loads(subprocess.check_output(['./infra/foundation/compose.sh', 'config', '--format', 'json'], cwd=ROOT))
    admin_env = {**os.environ, 'TEST_DATABASE_ADMIN_URL': 'postgresql://postgres:' + config['services']['postgres']['environment']['POSTGRES_PASSWORD'] + '@postgres:5432/postgres'}
    network = config['name'] + '_default'
    contracts = LOCAL / 'domain-contracts'
    run('python3', 'infra/foundation/package-contracts.py', str(contracts))
    private = subprocess.check_output(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048'], stderr=subprocess.DEVNULL)
    public = subprocess.check_output(['openssl', 'pkey', '-pubout'], input=private, stderr=subprocess.DEVNULL)
    for image in IMAGES.values():
        run('docker', 'image', 'inspect', image, stdout=subprocess.DEVNULL)
    compose, created = LOCAL / 'compose.json', []
    def mounts(service):
        return [f'{ROOT}/services/{service}/runtime/service_app:/app/service_app:ro',
            f'{ROOT}/services/{service}/modules:/app/modules:ro', f'{contracts}:/opt/domain-contracts:ro',
            f'{ROOT}/packages/runtime/src/bt_runtime/modules.py:/opt/venv/lib/python3.11/site-packages/bt_runtime/modules.py:ro']
    def helper(service, *arguments, extra_env=None):
        command = ['docker', 'run', '--rm', '--read-only', '--tmpfs', '/tmp', '--memory', '256m', '--cpus', '0.5',
            '--pids-limit', '128', '--network', network, '--user', f'{os.getuid()}:{os.getgid()}',
            '-e', 'PYTHONPATH=/app:/opt/domain-contracts', '-v', f'{ROOT}/tests/lanes/L14:/proof']
        for value in mounts(service):
            command += ['-v', value]
        env = {**admin_env, **(extra_env or {})}
        for name in ['TEST_DATABASE_ADMIN_URL', *(extra_env or {})]:
            command += ['-e', name]
        run(*command, IMAGES[service], 'python', *arguments, env=env)
    try:
        for service in IMAGES:
            created.append(service)
            helper(service, '/proof/proof_db.py', 'create', service, '/proof/.local/edit-connected')
        state = json.loads((LOCAL / 'db-orders.json').read_text())
        env = {'BT_DATABASE_URL': state['runtime_url'], 'BT_SERVICE_NAME': 'orders', 'BT_AUTH_PUBLIC_KEY': public.decode(),
            'BT_SERVICE_AUTH_PRIVATE_KEY': private.decode(), 'BT_SERVICE_AUTH_PUBLIC_KEY': public.decode(),
            'BT_AUTH_ISSUER': 'beirut-time-identity', 'BT_LOCAL_HTTP': '1', 'BT_SIMULATED_PAYMENT_SECRET': secrets.token_urlsafe(32)}
        for peer in ['identity', 'catalog', 'auction', 'pricing', 'communications', 'eligibility', 'trust', 'service-operations']:
            for prefix, suffix in [('', '_URL'), ('', '_API_URL'), ('BT_', '_URL')]:
                env[prefix + peer.upper().replace('-', '_') + suffix] = 'http://127.0.0.1:9'
        compose.write_text(json.dumps({'services': {'bt-l14-edit-orders': {'image': IMAGES['orders'],
            'command': ['uvicorn', 'bt_runtime.app.main:create_app', '--factory', '--host', '0.0.0.0', '--port', '8000', '--no-access-log'],
            'environment': env, 'ports': [f'127.0.0.1:{PORT}:8000'], 'networks': ['proof'],
            'volumes': mounts('orders'), 'read_only': True, 'tmpfs': ['/tmp'], 'mem_limit': '256m', 'cpus': .5, 'pids_limit': 100}},
            'networks': {'proof': {'external': True, 'name': network}}}))
        compose.chmod(0o600)
        run('docker', 'compose', '-p', 'bt-l14-edit-proof', '-f', str(compose), 'up', '-d', '--no-build')
        for _ in range(100):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/health/ready', timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, TimeoutError):
                pass
            time.sleep(.2)
        else:
            raise RuntimeError('Own Orders provider did not become ready')
        helper('auction', '/proof/edit_provider_check.py', extra_env={'BT_PROOF_PRIVATE_KEY': private.decode(),
            'BT_PROOF_PUBLIC_KEY': public.decode(), 'BT_PROOF_ORDERS_URL': 'http://bt-l14-edit-orders:8000'})
    finally:
        if compose.exists():
            run('docker', 'compose', '-p', 'bt-l14-edit-proof', '-f', str(compose), 'stop')
        for service in reversed(created):
            if (LOCAL / f'db-{service}.json').exists():
                helper(service, '/proof/proof_db.py', 'clean', service, '/proof/.local/edit-connected')
        if compose.exists():
            compose.unlink()


if __name__ == '__main__':
    main()
