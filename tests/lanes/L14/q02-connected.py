"""No-build Q02 real-service API proof; optional browser phase needs a fresh web build.

All accounts, approvals, listings, fees and physical reservations use their real
commands. Only Identity's documented one-time local operator bootstrap is used.
"""
import argparse
import json
import os
import secrets
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from q02_prepare import prepare

ROOT = Path(__file__).resolve().parents[3]
LOCAL = ROOT / 'tests/lanes/L14/.local/q02-connected'
ORIGIN = 'http://127.0.0.1:3640'
PORTS = {'identity': 3641, 'catalog': 3642, 'pricing': 3643, 'orders': 3644}
IMAGES = {'identity': os.environ.get('BT_L14_IDENTITY_IMAGE', 'beirut-time/accept-identity:local'),
    'catalog': os.environ.get('BT_L14_CATALOG_IMAGE', 'beirut-time/catalog:test-9376f15f-70339'),
    'pricing': os.environ.get('BT_L14_PRICING_IMAGE', 'beirut-time/l14-pricing:proof'),
    'orders': os.environ.get('BT_L14_ORDERS_IMAGE', 'beirut-time/orders:test-42bf19f1-23729')}


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def ready(url):
    for _ in range(120):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(.2)
    raise RuntimeError('Own Q02 service did not become ready: ' + url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true', help='Requires a successful current web production build; performs no build')
    parser.add_argument('--guest-return', action='store_true', help='Require the shared Identity guest-return integration after its owner handoff')
    args = parser.parse_args()
    if args.guest_return and not args.browser:
        parser.error('--guest-return requires --browser')
    LOCAL.mkdir(parents=True, exist_ok=True)
    LOCAL.chmod(0o700)
    if list(LOCAL.glob('db-*.json')):
        raise RuntimeError('Clean the own previous Q02 run before creating more databases')
    for port in [*PORTS.values(), *([3640] if args.browser else [])]:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    config = json.loads(subprocess.check_output(['./infra/foundation/compose.sh', 'config', '--format', 'json'], cwd=ROOT))
    admin_env = {**os.environ, 'TEST_DATABASE_ADMIN_URL': 'postgresql://postgres:' + config['services']['postgres']['environment']['POSTGRES_PASSWORD'] + '@postgres:5432/postgres'}
    network = config['name'] + '_default'
    contracts = LOCAL / 'domain-contracts'
    run('python3', 'infra/foundation/package-contracts.py', str(contracts))
    for image in IMAGES.values():
        run('docker', 'image', 'inspect', image, stdout=subprocess.DEVNULL)
    private = subprocess.check_output(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048'], stderr=subprocess.DEVNULL)
    public = subprocess.check_output(['openssl', 'pkey', '-pubout'], input=private, stderr=subprocess.DEVNULL)
    compose, created, web, web_log = LOCAL / 'compose.json', [], None, None
    def mounts(service):
        return [f'{ROOT}/services/{service}/runtime/service_app:/app/service_app:ro',
            f'{ROOT}/services/{service}/modules:/app/modules:ro', f'{contracts}:/opt/domain-contracts:ro',
            f'{ROOT}/packages/runtime/src/bt_runtime/modules.py:/opt/venv/lib/python3.11/site-packages/bt_runtime/modules.py:ro']
    def database(action, service):
        command = ['docker', 'run', '--rm', '--read-only', '--tmpfs', '/tmp', '--network', network,
            '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'TEST_DATABASE_ADMIN_URL', '-e', 'PYTHONPATH=/app:/opt/domain-contracts',
            '-v', f'{ROOT}/tests/lanes/L14:/proof']
        for value in mounts(service):
            command += ['-v', value]
        run(*command, IMAGES[service], 'python', '/proof/proof_db.py', action, service, '/proof/.local/q02-connected', env=admin_env)
    try:
        for service in IMAGES:
            created.append(service)
            database('create', service)
        services = {}
        for service, image in IMAGES.items():
            state = json.loads((LOCAL / f'db-{service}.json').read_text())
            env = {'BT_DATABASE_URL': state['runtime_url'], 'BT_SERVICE_NAME': service, 'BT_AUTH_PRIVATE_KEY': private.decode(),
                'BT_AUTH_PUBLIC_KEY': public.decode(), 'BT_SERVICE_AUTH_PRIVATE_KEY': private.decode(), 'BT_SERVICE_AUTH_PUBLIC_KEY': public.decode(),
                'BT_AUTH_ISSUER': 'beirut-time-identity', 'BT_AUTH_AUDIENCE': 'beirut-time', 'BT_LOCAL_HTTP': '1',
                'BT_ALLOWED_WEB_ORIGINS': ORIGIN, 'BT_PUBLIC_WEB_ORIGINS': ORIGIN, 'BT_ENVIRONMENT': 'demo',
                'BT_SIMULATED_PAYMENT_SECRET': secrets.token_urlsafe(32)}
            for peer in ['identity', 'catalog', 'pricing', 'orders', 'auction', 'communications', 'eligibility', 'trust', 'service-operations']:
                url = 'http://bt-l14-q02-' + peer + ':8000' if peer in IMAGES else 'http://127.0.0.1:9'
                for prefix, suffix in [('', '_URL'), ('', '_API_URL'), ('BT_', '_URL')]:
                    env[prefix + peer.upper().replace('-', '_') + suffix] = url
            factory = 'service_app.main:create_app' if service in ('identity', 'pricing') else 'bt_runtime.app.main:create_app'
            services['bt-l14-q02-' + service] = {'image': image, 'command': ['uvicorn', factory, '--factory', '--host', '0.0.0.0', '--port', '8000', '--no-access-log'],
                'environment': env, 'ports': [f'127.0.0.1:{PORTS[service]}:8000'], 'networks': ['proof'], 'volumes': mounts(service),
                'read_only': True, 'tmpfs': ['/tmp'], 'mem_limit': '256m', 'cpus': .5, 'pids_limit': 100}
        compose.write_text(json.dumps({'services': services, 'networks': {'proof': {'external': True, 'name': network}}}))
        compose.chmod(0o600)
        run('docker', 'compose', '-p', 'bt-l14-q02-proof', '-f', str(compose), 'up', '-d', '--no-build')
        for port in PORTS.values():
            ready(f'http://127.0.0.1:{port}/health/ready')
        def bootstrap(email):
            run('docker', 'compose', '-p', 'bt-l14-q02-proof', '-f', str(compose), 'exec', '-T', 'bt-l14-q02-identity',
                'python', '-m', 'service_app.bootstrap_operator', '--email', email, '--reason', 'Sample isolated Q02 validation; no production capability')
        evidence, browser = prepare(PORTS, ORIGIN, bootstrap, browser_positive=args.browser)
        (LOCAL / 'api-evidence.json').write_text(json.dumps(evidence, indent=2))
        if args.browser:
            browser['check_guest_return'] = args.guest_return
            env = {**os.environ, 'BT_PUBLIC_WEB_ORIGINS': ORIGIN, 'BT_ALLOWED_WEB_ORIGINS': ORIGIN}
            for peer in ['identity', 'catalog', 'pricing', 'orders', 'auction', 'communications', 'eligibility', 'trust', 'service-operations']:
                env[peer.upper().replace('-', '_') + '_API_URL'] = f'http://127.0.0.1:{PORTS[peer]}' if peer in PORTS else 'http://127.0.0.1:9'
            web_log = (LOCAL / 'web.log').open('w')
            web = subprocess.Popen(['node', 'node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', '3640'],
                cwd=ROOT / 'web', env=env, stdout=web_log, stderr=subprocess.STDOUT)
            ready(ORIGIN + '/en/offers')
            run('bash', 'tests/lanes/L14/offers-browser.sh', env={**env, 'BT_L14_BROWSER_CONTEXT': json.dumps(browser)})
        print('Q02 isolated API checks passed: exactly one reservation in contention; self, client deadline, stale and blocked requests denied. Durable payment-notice transition withheld: Communications is not in this stack. No payment invoked.')
    finally:
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
            run('docker', 'compose', '-p', 'bt-l14-q02-proof', '-f', str(compose), 'stop')
        for service in reversed(created):
            if (LOCAL / f'db-{service}.json').exists():
                database('clean', service)
        if compose.exists():
            compose.unlink()


if __name__ == '__main__':
    main()
