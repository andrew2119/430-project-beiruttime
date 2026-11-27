"""Start or stop the nine services and the production web on this runner.

Usage:
  python .github/ci/stack.py start <run-dir>
  python .github/ci/stack.py stop <run-dir>

start expects the job's PostgreSQL on 127.0.0.1:54329 with the service databases created
(.github/ci/db-init.sh) and a production web build in web/.next.
It generates disposable keys, applies each service's migrations as its owner, starts each
service with one worker and the web server, waits for every readiness endpoint, and writes
the private native-v1.json settings file the connected walkthrough reads.
"""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_ci import ROOT, SERVICES, SHARED, common_environment, database_urls, package_contracts  # noqa: E402
from checks_http import ready  # noqa: E402

PRIVATE_KEYS = ('BT_AUTH_PRIVATE_KEY', 'BT_EVENT_PRIVATE_KEY', 'BT_SERVICE_AUTH_PRIVATE_KEY',
                'BT_AUCTION_SERVICE_AUTH_PRIVATE_KEY', 'BT_PRICING_EVENT_PRIVATE_KEY',
                'BT_TRUST_SERVICE_PRIVATE_KEY', 'BT_INTAKE_SERVICE_PRIVATE_KEY')
ADMIN_ONLY = ('TEST_DATABASE_ADMIN_URL', 'PGPASSWORD', 'PGUSER', 'POSTGRES_USER', 'OWNER_URL')
MANIFEST_KEYS = re.compile(r'^(BT_[A-Z0-9_]+|[A-Z0-9_]+_URL|[A-Z0-9_]+_API_URL|AUCTION_[A-Z0-9_]+|CATALOG_[A-Z0-9_]+)$')
PORTS = [3000] + [s['port'] for s in SERVICES]


def keys(run):
    folder = run / 'keys'
    folder.mkdir(mode=0o700, exist_ok=True)
    pair = {}
    for name in ('user', 'event'):
        private, public = folder / f'{name}.pem', folder / f'{name}.pub'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(private)],
                       check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)], check=True,
                       capture_output=True)
        pair[name] = (private.read_text(), public.read_text())
    return pair


def base_environment(run, contracts):
    pair = keys(run)
    env = dict(os.environ)
    env.update(common_environment())
    event_private, event_public = pair['event']
    env.update(BT_AUTH_PRIVATE_KEY=pair['user'][0], BT_AUTH_PUBLIC_KEY=pair['user'][1],
               BT_EVENT_PRIVATE_KEY=event_private, BT_SERVICE_AUTH_PUBLIC_KEY=event_public,
               AUCTION_HIGH_VALUE_USD_MINOR='1000000', AUCTION_HIGH_VALUE_LBP_MINOR='89500000000',
               CATALOG_MEDIA_API_URL='http://127.0.0.1:8102', BT_ENVIRONMENT='demo', BT_REQUEST_BODY_LIMIT='8500000',
               BT_DEMO_MANIFEST=str(ROOT / 'demo/images-manifest.json'), BT_DEMO_ROOT=str(run / 'demo'))
    for name in PRIVATE_KEYS[2:]:
        env[name] = event_private
    for service in SERVICES:
        key = service['name'].replace('-', '_').upper()
        url = f"http://127.0.0.1:{service['port']}"
        env.update({f'{key}_URL': url, f'{key}_API_URL': url, f'BT_{key}_URL': url, f'BT_{key}_API_URL': url})
    env['PYTHONPATH'] = ':'.join(map(str, [contracts, *SHARED]))
    return env


def service_environment(base, name, contracts):
    runtime = ROOT / 'services' / name / 'runtime'
    database, owner = database_urls(name)
    env = dict(base, BT_SERVICE_NAME=name, BT_DATABASE_URL=database, TEST_RUNTIME_URL=database, OWNER_URL=owner,
               BT_MODULES_PATH=str(runtime.parent / 'modules'),
               PYTHONPATH=':'.join(map(str, [runtime, runtime.parent, contracts, *SHARED])))
    if name != 'identity':
        env.pop('BT_AUTH_PRIVATE_KEY', None)
    return env


def spawn(command, env, cwd, log):
    with open(log, 'ab') as stream:
        return subprocess.Popen(command, env=env, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True).pid


def tails(run):
    for log in sorted(run.glob('*.log')):
        lines = log.read_text(errors='replace').splitlines()[-30:]
        print(f'::group::{log.name}')
        print('\n'.join(lines))
        print('::endgroup::')


def start(run):
    run.mkdir(parents=True, exist_ok=True)
    contracts = package_contracts(None, run)
    link = run / 'domain-contracts'
    if not link.exists():
        link.symlink_to(contracts)
    demo = run / 'demo'
    demo.mkdir(exist_ok=True)
    for name in ('images-manifest.json', 'listings.json'):
        shutil.copy2(ROOT / 'demo' / name, demo / name)
    shutil.copytree(ROOT / 'web/public/demo/watches', demo / 'watches', dirs_exist_ok=True)
    base = base_environment(run, contracts)
    python = sys.executable
    pids, manifest = {}, {}
    for service in SERVICES:
        name = service['name']
        runtime = ROOT / 'services' / name / 'runtime'
        env = service_environment(base, name, contracts)
        print(f'migrate {name}', flush=True)
        subprocess.run([python, '-m', 'service_app.migrate'], env=dict(env, BT_DATABASE_URL=env['OWNER_URL']),
                       cwd=runtime, check=True, timeout=120)
        running = {k: v for k, v in env.items() if k not in ADMIN_ONLY}
        command = [python, '-m', 'uvicorn', service['factory'], '--factory', '--host', '127.0.0.1',
                   '--port', str(service['port']), '--workers', '1', '--no-access-log']
        pids[name] = spawn(command, running, runtime, run / f'{name}.log')
        (run / 'pids.json').write_text(json.dumps(pids))
        recorded = {k: v for k, v in env.items() if MANIFEST_KEYS.match(k) and k != 'BT_MODULES_PATH'}
        recorded['BT_DATABASE_OWNER_URL'] = env['OWNER_URL']
        manifest[name] = {'env': recorded}
    target = run / 'native-v1.json'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'schema_version': 1, 'services': manifest}, stream)
    web = {k: v for k, v in base.items() if k not in (*ADMIN_ONLY, *PRIVATE_KEYS)}
    pids['web'] = spawn(['node', 'node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', '3000'],
                        web, ROOT / 'web', run / 'web.log')
    (run / 'pids.json').write_text(json.dumps(pids))
    try:
        ready(90)
    except Exception:
        tails(run)
        raise
    print('All nine services and the web server are ready.')


def listening(port):
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(('127.0.0.1', port)) == 0


def stop(run):
    pids = json.loads((run / 'pids.json').read_text()) if (run / 'pids.json').is_file() else {}
    for pid in pids.values():
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and any(listening(p) for p in PORTS):
        time.sleep(0.5)
    for pid in pids.values():
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    busy = [p for p in PORTS if listening(p)]
    if busy:
        raise SystemExit(f'ports still listening after stop: {busy}')
    print('Stack stopped; ports 3000 and 8101-8109 are free.')


if __name__ == '__main__':
    action, folder = sys.argv[1], Path(sys.argv[2])
    {'start': start, 'stop': stop}[action](folder)
