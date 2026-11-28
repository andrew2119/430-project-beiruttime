"""Run with bt-heavy.sh: private restricted DBs, three own containers, real web.

This proves boot and actual empty/private shell behavior only. Populated offer
and assessment acceptance must additionally use the merged domain providers.
"""
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCAL = ROOT / 'tests/lanes/L14/.local'
ORIGIN = 'http://127.0.0.1:3610'
IMAGES = {'identity': os.environ.get('BT_L14_IDENTITY_IMAGE', 'beirut-time/identity:local'),
          'pricing': os.environ.get('BT_L14_PRICING_IMAGE', 'beirut-time/l14-pricing:proof'),
          'auction': os.environ.get('BT_L14_AUCTION_IMAGE', 'beirut-time/l14-auction:proof')}
PORTS = {'identity': 3611, 'pricing': 3614, 'auction': 3613}


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def ready(url):
    for _ in range(100):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(.2)
    raise RuntimeError('Local readiness did not pass: ' + url)


def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    os.chmod(LOCAL, 0o700)
    for port in [3610, *PORTS.values()]:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    config = json.loads(subprocess.check_output(['./infra/foundation/compose.sh', 'config', '--format', 'json'], cwd=ROOT))
    admin_env = {**os.environ, 'TEST_DATABASE_ADMIN_URL': 'postgresql://postgres:' + config['services']['postgres']['environment']['POSTGRES_PASSWORD'] + '@postgres:5432/postgres'}
    network = config['name'] + '_default'
    # Dependency closure was already built. Source-only checks reuse those
    # images with read-only binds instead of growing the shared image store.
    contracts = LOCAL / 'domain-contracts'
    run('python3', 'infra/foundation/package-contracts.py', str(contracts))
    for image in IMAGES.values():
        run('docker', 'image', 'inspect', image, stdout=subprocess.DEVNULL)
    private = subprocess.check_output(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048'], stderr=subprocess.DEVNULL)
    public = subprocess.check_output(['openssl', 'pkey', '-pubout'], input=private, stderr=subprocess.DEVNULL)
    created = []
    compose = LOCAL / 'proof.compose.json'
    web = None
    web_log = None
    def database(action, service):
        run('docker', 'run', '--rm', '--network', network, '--user', f'{os.getuid()}:{os.getgid()}',
            '-e', 'TEST_DATABASE_ADMIN_URL', '-v', f'{ROOT}/tests/lanes/L14:/proof',
            '-v', f'{ROOT}/services/{service}/runtime/service_app:/app/service_app:ro',
            '-v', f'{ROOT}/services/{service}/modules:/app/modules:ro',
            '-v', f'{contracts}:/opt/domain-contracts:ro', IMAGES[service],
            'python', '/proof/proof_db.py', action, service, '/proof/.local', env=admin_env)
    try:
        for service in IMAGES:
            database('create', service)
            created.append(service)
        services = {}
        for service, image in IMAGES.items():
            db = json.loads((LOCAL / f'db-{service}.json').read_text())
            env = {'BT_DATABASE_URL': db['runtime_url'], 'BT_SERVICE_NAME': service,
                'BT_AUTH_PRIVATE_KEY': private.decode(), 'BT_AUTH_PUBLIC_KEY': public.decode(),
                'BT_SERVICE_AUTH_PRIVATE_KEY': private.decode(), 'BT_SERVICE_AUTH_PUBLIC_KEY': public.decode(),
                'BT_AUTH_ISSUER': 'beirut-time-identity', 'BT_AUTH_AUDIENCE': 'beirut-time', 'BT_LOCAL_HTTP': '1',
                'BT_ALLOWED_WEB_ORIGINS': ORIGIN, 'BT_PUBLIC_WEB_ORIGINS': ORIGIN,
                'IDENTITY_API_URL': 'http://bt-l14-identity:8000', 'IDENTITY_URL': 'http://bt-l14-identity:8000'}
            for peer in ['catalog', 'orders', 'communications', 'service-operations', 'auction', 'pricing']:
                slug = peer.upper().replace('-', '_')
                env[slug + '_API_URL'] = 'http://127.0.0.1:9'
                env[slug + '_URL'] = 'http://127.0.0.1:9'
            services['bt-l14-' + service] = {'image': image, 'command': ['uvicorn', 'service_app.main:create_app', '--factory',
                '--host', '0.0.0.0', '--port', '8000', '--no-access-log'], 'environment': env,
                'ports': [f'127.0.0.1:{PORTS[service]}:8000'], 'networks': ['proof'],
                'volumes': [f'{ROOT}/services/{service}/runtime/service_app:/app/service_app:ro',
                    f'{ROOT}/services/{service}/modules:/app/modules:ro', f'{contracts}:/opt/domain-contracts:ro'], 'read_only': True,
                'tmpfs': ['/tmp'], 'mem_limit': '256m', 'cpus': .5, 'pids_limit': 100}
        compose.write_text(json.dumps({'services': services, 'networks': {'proof': {'external': True, 'name': network}}}))
        compose.chmod(0o600)
        run('docker', 'compose', '-p', 'bt-l14-proof', '-f', str(compose), 'up', '-d', '--no-build')
        for port in PORTS.values():
            ready(f'http://127.0.0.1:{port}/health/ready')
        env = {**os.environ, 'BT_PUBLIC_WEB_ORIGINS': ORIGIN, 'BT_ALLOWED_WEB_ORIGINS': ORIGIN}
        for name in ['identity', 'pricing', 'auction', 'catalog', 'orders', 'eligibility', 'trust', 'communications', 'service-operations']:
            env[name.upper().replace('-', '_') + '_API_URL'] = f'http://127.0.0.1:{PORTS[name]}' if name in PORTS else 'http://127.0.0.1:9'
        web_log = (LOCAL / 'proof-web.log').open('w')
        web = subprocess.Popen(['node', 'node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', '3610'],
                               cwd=ROOT / 'web', env=env, stdout=web_log, stderr=subprocess.STDOUT)
        ready(ORIGIN + '/en/offers')
        run('bash', 'tests/lanes/L14/browser-matrix.sh', env=env)
        (LOCAL / 'shell-proof.json').write_text(json.dumps({'result': 'passed', 'scope': 'real private empty-state matrix; no populated acceptance',
            'matrix_cases': 24, 'images': IMAGES, 'ports': PORTS}, indent=2))
    finally:
        run('chrome-devtools-axi', 'stop', env={**os.environ, 'CHROME_DEVTOOLS_AXI_SESSION': 'bt-s2-l14'}, stdout=subprocess.DEVNULL)
        if web:
            web.terminate()
            try:
                web.wait(timeout=10)
            except subprocess.TimeoutExpired:
                web.kill()
                web.wait()
        if web_log:
            web_log.close()
        if compose.exists():
            run('docker', 'compose', '-p', 'bt-l14-proof', '-f', str(compose), 'stop')
        for service in reversed(created):
            database('clean', service)
        if compose.exists():
            compose.unlink()


if __name__ == '__main__':
    main()
