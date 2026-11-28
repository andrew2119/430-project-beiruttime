"""Shared constants for the Beirut Time CI helpers."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / 'scripts/native-services.json').read_text())
SERVICES = [s for s in MANIFEST['services'] if s['name'] != 'web']
NAMES = [s['name'] for s in SERVICES]
SHARED = [ROOT / 'packages' / p / 'src' for p in ('runtime', 'events', 'bulkheads', 'contracts-core')]
PG = '127.0.0.1:54329'
ADMIN_PASSWORD = 'local-bootstrap-only'
ORIGIN = 'http://localhost:3000'
ORIGINS = ORIGIN + ',http://127.0.0.1:3000'


def slug(name):
    return 'service_ops' if name == 'service-operations' else name


def password(name):
    return 'local-service-ops' if name == 'service-operations' else 'local-' + name


def database_urls(name):
    s, pw = slug(name), password(name)
    return (f'postgresql://bt_{s}:{pw}@{PG}/bt_{s}', f'postgresql://bt_{s}_owner:{pw}-owner@{PG}/bt_{s}')


def common_environment():
    """Values every service and the web process share, as the native runs set them."""
    return dict(
        LANG='C.UTF-8', LC_ALL='C.UTF-8', TZ='UTC', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1',
        NEXT_TELEMETRY_DISABLED='1', NODE_OPTIONS='--max-old-space-size=4096', UV_THREADPOOL_SIZE='2',
        OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
        PGHOST='127.0.0.1', PGPORT='54329', PGUSER='postgres', PGDATABASE='postgres', POSTGRES_USER='postgres',
        PGPASSWORD=ADMIN_PASSWORD, TEST_DATABASE_ADMIN_URL=f'postgresql://postgres:{ADMIN_PASSWORD}@{PG}/postgres',
        BT_AUTH_ISSUER='beirut-time-identity', BT_AUTH_AUDIENCE='beirut-time', BT_DATABASE_POOL_SIZE='3',
        BT_WEB_ORIGIN=ORIGIN, BT_ALLOWED_WEB_ORIGINS=ORIGINS, BT_PUBLIC_WEB_ORIGINS=ORIGINS,
        BT_TRUST_FORWARDED_ORIGIN='false', BT_LOCAL_HTTP='1', BT_CONTACT_SIMULATOR='1')


def package_contracts(service, work):
    """Return the contracts directory for a service, building it once per work directory."""
    import subprocess
    import sys
    own = ROOT / 'services' / service / 'runtime/package_contracts.py' if service else None
    target = work / (f'contracts-{service}' if own and own.is_file() else 'contracts')
    if not (target / 'bt_contracts').is_dir():
        if own and own.is_file():
            command = [sys.executable, str(own), str(ROOT), str(target)]
        else:
            command = [sys.executable, str(ROOT / 'infra/foundation/package-contracts.py'), str(target)]
        subprocess.run(command, check=True, cwd=ROOT)
    return target


def ids_digest(ids):
    return hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()


def write_report(path, suite, ok, problems=(), **counts):
    """Write the one-line report a job publishes as its output."""
    data = dict(suite=suite, ok=bool(ok), problems=list(problems)[:20], **counts)
    line = json.dumps(data, sort_keys=True, separators=(',', ':'))
    Path(path).write_text(line + '\n')
    print(line)
    return 0 if ok else 1


def work_dir(name):
    base = Path(os.environ.get('RUNNER_TEMP') or '/tmp')
    path = base / f'bt-{name}'
    path.mkdir(parents=True, exist_ok=True)
    return path
