"""Private native execution. Connected commands require a held external lock.

Capability v1: --capability names a private JSON document with schema_version=1,
python, postgres_bin, batch_id, and environment (explicit runtime settings).
Admission v1 must be installed at the fixed contract location.
Start stays in the foreground to supervise admission for the entire batch.
Production web output must already exist. No build or dependency installation occurs.
Ledger v1 retains process sessions and kernel start ticks, never credentials.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import re
import subprocess
import sys
import time
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'scripts/native-services.json').read_text())


def select(value):
    names = value.split(',')
    known = {s['name']: s for s in MANIFEST['services']}
    if len(set(names)) != len(names) or any(n not in known for n in names):
        raise ValueError('Invalid services list')
    return [known[n] for n in names]


def plan(services):
    return {'schema_version': 1, 'host': MANIFEST['host'],
            'database': MANIFEST['database'], 'services': services,
            'phases': ['verify-pins', 'new-private-cluster', 'initialize-nine-databases',
                       'package-current-contracts', 'owner-migrations', 'runtime-only-launch', 'readiness'],
            'databases': ['bt_' + s['database'] for s in MANIFEST['services'] if 'database' in s]}


def ticks(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except FileNotFoundError:
        return None


def members(entry):
    """A session remains reserved while any non-zombie member survives."""
    found = []
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rsplit(')', 1)[1].split()
            if (int(fields[3]) == entry['pid'] and fields[0] != 'Z'
                    and int(fields[19]) >= int(entry['start_ticks'])):
                found.append(int(path.parent.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return found


def owned(entry):
    if entry.get('finished') or entry.get('start_ticks') is None:
        return False
    current = ticks(entry['pid'])
    if current is not None and current != entry['start_ticks']:
        return False
    return bool(members(entry))


def save(run, ledger):
    temporary = run / 'ledger.tmp'
    with temporary.open('w') as out:
        json.dump(ledger, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(run / 'ledger.json')


def available(port):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))


ADMISSION = Path('/opt/domain-contracts/native-admission-v1.json')


def admission(cap):
    """Admission v1 is installed by the batch owner, never selected by callers.

    The marker binds batch_id, lock device/inode, holder pid/start ticks and
    expires_at. The kernel must report that holder's exclusive whole-file lock.
    Missing contract, expired admission or replaced lock fails closed.
    """
    metadata = ADMISSION.stat()
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ValueError('Admission contract is not protected')
    marker = json.loads(ADMISSION.read_text())
    if (marker['schema_version'] != 1 or marker['state'] != 'closed'
            or marker['batch_id'] != cap['batch_id']
            or time.time() >= marker['expires_at']
            or ticks(marker['pid']) != marker['start_ticks']):
        raise ValueError('Batch admission is unavailable')
    stat = Path(marker['lock']).stat()
    identity = f"{os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}:{stat.st_ino}"
    if identity != marker['lock_identity']:
        raise ValueError('Batch lock was replaced')
    expected = ['FLOCK', 'ADVISORY', 'WRITE', str(marker['pid']), identity, '0', 'EOF']
    if not any(row.split()[1:] == expected for row in Path('/proc/locks').read_text().splitlines()):
        raise ValueError('Exclusive batch lock is not held')


def capability(path):
    cap = json.loads(Path(path).read_text())
    if cap['schema_version'] != 1:
        raise ValueError('Unsupported capability')
    admission(cap)
    return cap


def environment(cap, run, service=None, owner=False):
    env = {'PATH': str(Path(cap['python']).parent) + ':' + cap['postgres_bin'] + ':/usr/bin:/bin',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1'}
    extra = dict(cap.get('environment', {}))
    extra.update(cap.get('service_environment', {}).get(service['name'] if service else 'database', {}))
    if service and service['name'] == 'web' and any('KEY' in k or 'TOKEN' in k or 'SECRET' in k for k in extra):
        raise ValueError('Private settings are forbidden for web')
    if any('PASSWORD' in k or 'DATABASE' in k or k.startswith('PG') for k in extra):
        raise ValueError('Database overrides are forbidden')
    if any('KEY' in k or 'TOKEN' in k or 'SECRET' in k for k in cap.get('environment', {})):
        raise ValueError('Private settings require a service scope')
    env.update(extra)
    for item in MANIFEST['services']:
        key = item['name'].upper().replace('-', '_')
        for alias in (key + '_URL', key + '_API_URL', 'BT_' + key + '_URL', 'BT_' + key + '_API_URL'):
            env[alias] = f"http://127.0.0.1:{item['port']}"
    env.update(BT_PUBLIC_WEB_ORIGINS=','.join(MANIFEST['origins']),
               BT_ALLOWED_WEB_ORIGINS=','.join(MANIFEST['origins']),
               BT_WEB_ORIGIN=MANIFEST['origins'][0], BT_LOCAL_HTTP='1',
               BT_TRUST_FORWARDED_ORIGIN='false', HOSTNAME='127.0.0.1', PORT='3000',
               NODE_ENV='production')
    if service and 'database' in service:
        slug = service['database']
        password = 'local-' + slug.replace('_', '-') + ('-owner' if owner else '')
        role = 'bt_' + slug + ('_owner' if owner else '')
        env['BT_DATABASE_URL'] = f'postgresql://{role}:{password}@127.0.0.1:54329/bt_{slug}'
        env['BT_SERVICE_NAME'] = service['name']
        env['BT_MODULES_PATH'] = str(ROOT / 'services' / service['name'] / 'modules')
        env['PYTHONPATH'] = os.pathsep.join([str(run / 'contracts'), str(ROOT / 'services' / service['name'] / 'runtime'),
            str(ROOT / 'services' / service['name'])] +
            [str(ROOT / 'packages' / p / 'src') for p in ('runtime', 'bulkheads', 'events', 'contracts-core')])
        env['CATALOG_MEDIA_API_URL'] = 'http://127.0.0.1:8102'
    return env


READERS = {}


def launch(run, ledger, name, command, env):
    pending = []
    previous = {number: signal.signal(number, lambda number, frame: pending.append(number))
                for number in (signal.SIGINT, signal.SIGTERM)}
    child = None
    entry = None
    try:
        with (run / (name + '.log')).open('a') as log:
            log_path = Path(log.name)
            log_path.chmod(0o600)
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, start_new_session=True,
                                     restore_signals=True)
        entry = {'name': name, 'pid': child.pid, 'start_ticks': None}
        ledger['processes'].append(entry)
        save(run, ledger)
        entry['start_ticks'] = ticks(child.pid)
        save(run, ledger)
        if entry['start_ticks'] is None:
            raise RuntimeError('Process identity capture failed')
        reader = threading.Thread(target=diagnostics, args=(child.stdout, log_path, env), daemon=True)
        reader.start()
        child.diagnostic_reader = reader
        READERS[child.pid] = reader
        return child
    except BaseException:
        if child is not None:
            if entry is not None and owned(entry):
                signal_session(entry, signal.SIGKILL)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            if entry is None or entry['start_ticks'] is None:
                ledger['cleanup_complete'] = False
                ledger['state'] = 'cleanup-incomplete'
                save(run, ledger)
        raise
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
        if pending:
            raise KeyboardInterrupt


def signal_session(entry, number):
    try:
        os.killpg(entry['pid'], number)
    except ProcessLookupError:
        pass
    # Session children can create additional groups after their leader exits.
    for pid in members(entry):
        stamp = ticks(pid)
        if stamp is not None and pid in members(entry) and ticks(pid) == stamp:
            try:
                os.kill(pid, number)
            except ProcessLookupError:
                pass


def stop(run, ledger):
    incomplete = False
    for entry in reversed(ledger['processes']):
        if entry.get('start_ticks') is None:
            incomplete = True
        if owned(entry):
            signal_session(entry, signal.SIGTERM)
            until = time.monotonic() + 10
            while owned(entry) and time.monotonic() < until:
                time.sleep(.1)
            if owned(entry):
                signal_session(entry, signal.SIGKILL)
            until = time.monotonic() + 5
            while owned(entry) and time.monotonic() < until:
                time.sleep(.1)
            incomplete = owned(entry) or incomplete
        reader = READERS.get(entry['pid'])
        if reader is not None:
            reader.join(timeout=5)
            incomplete = reader.is_alive() or incomplete
    ledger['cleanup_complete'] = not incomplete
    ledger['state'] = 'cleanup-incomplete' if incomplete else 'stopped'
    save(run, ledger)
    # Retain private data and logs for diagnosis; no recursive deletion.


def wait_ready(url, child, cap=None):
    until = time.monotonic() + 60
    while time.monotonic() < until:
        if cap is not None:
            admission(cap)
        if child.poll() is not None:
            raise RuntimeError('Owned process exited during startup')
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(.2)
    raise RuntimeError('Readiness deadline exceeded')


def redact(text, settings):
    secrets = ['local-' + item['database'].replace('_', '-') + suffix
               for item in MANIFEST['services'] if 'database' in item
               for suffix in ('', '-owner')]
    for key, value in settings.items():
        if any(word in key for word in ('PASSWORD', 'SECRET', 'TOKEN', 'KEY', 'DATABASE_URL')):
            secrets.append(value)
            secrets.extend(value.splitlines())
            if 'DATABASE_URL' in key:
                from urllib.parse import urlsplit
                secrets.append(urlsplit(value).password or '')
    for value in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(value, '[redacted]')
    return re.sub(r'postgres(?:ql)?://[^\s]+', '[redacted]', text)


def diagnostics(stream, path, settings):
    # Raw subprocess output never reaches disk.
    with stream, path.open('a') as log:
        for line in iter(stream.readline, b''):
            log.write(redact(line.decode(errors='replace'), settings))
            log.flush()


def restrict_auth(run):
    # Reject all socket access and require each password over loopback.
    (run / 'data/pg_hba.conf').write_text(
        'local all all reject\n'
        'host all postgres 127.0.0.1/32 reject\n'
        'host all all 127.0.0.1/32 scram-sha-256\n'
        'host all all ::1/128 reject\n')


def database_ready(pg, run, env, child, cap):
    until = time.monotonic() + 30
    while True:
        admission(cap)
        if child.poll() is not None or time.monotonic() > until:
            raise RuntimeError('Private database readiness failed')
        result = subprocess.run([str(pg / 'pg_isready'), '-h', str(run), '-p', '54329'],
                                env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=3)
        if result.returncode == 0:
            return
        time.sleep(.2)


def supervise(run, ledger, cap):
    with (run / 'control.lock').open('a') as control:
        while True:
            try:
                fcntl.flock(control, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(.1)
                continue
            try:
                current = json.loads((run / 'ledger.json').read_text())
                if current['state'] == 'stopped' and current.get('cleanup_complete'):
                    for entry in ledger['processes']:
                        reader = READERS.get(entry['pid'])
                        if reader is not None:
                            reader.join(timeout=5)
                            if reader.is_alive():
                                raise RuntimeError('Diagnostics remain incomplete')
                    return
                admission(cap)
                if not all(owned(e) for e in ledger['processes'] if not e.get('finished')):
                    raise RuntimeError('A required session exited')
            finally:
                fcntl.flock(control, fcntl.LOCK_UN)
            time.sleep(.1)


def cleanup_lock(control):
    deadline = time.monotonic() + 240
    while True:
        try:
            fcntl.flock(control, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise RuntimeError('Cleanup control remains occupied')
            time.sleep(.1)


def start(run, services, cap):
    admission(cap)
    for port in [54329] + [s['port'] for s in services]:
        available(port)
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    ledger = {'schema_version': 1, 'state': 'starting', 'services': services, 'processes': []}
    save(run, ledger)
    control = (run / 'control.lock').open('a')
    fcntl.flock(control, fcntl.LOCK_EX | fcntl.LOCK_NB)
    env = {}
    pg = Path(cap['postgres_bin'])
    def command(args, settings=env):
        admission(cap)
        name = 'prepare-' + str(len(ledger['processes']))
        child = launch(run, ledger, name, args, settings)
        try:
            deadline = time.monotonic() + 120
            while child.poll() is None:
                admission(cap)
                if time.monotonic() >= deadline:
                    raise RuntimeError('Preparation deadline exceeded')
                time.sleep(.1)
            result = child.wait(timeout=5)
        finally:
            if child.poll() is not None:
                child.diagnostic_reader.join(timeout=5)
                if child.diagnostic_reader.is_alive():
                    raise RuntimeError('Preparation diagnostics remain incomplete')
        ledger['processes'][-1]['exit_code'] = result
        save(run, ledger)
        if result:
            raise RuntimeError('Preparation failed')
        if owned(ledger['processes'][-1]):
            raise RuntimeError('Preparation left surviving descendants')
        ledger['processes'][-1]['finished'] = True
        save(run, ledger)
    try:
        env.update(environment(cap, run))
        version = subprocess.check_output([str(pg / 'postgres'), '--version'], env=env, timeout=5).decode()
        if not version.split()[-1].startswith('17.'):
            raise ValueError('Database major version must be 17')
        command([str(pg / 'initdb'), '-D', str(run / 'data'), '-U', 'postgres',
                 '--encoding=UTF8', '--no-locale', '--auth-local=trust', '--auth-host=reject'])
        child = launch(run, ledger, 'database', [str(pg / 'postgres'), '-D', str(run / 'data'),
                       '-h', '', '-p', '54329', '-k', str(run)], env)
        database_ready(pg, run, env, child, cap)
        initial = dict(env, PGHOST=str(run), PGPORT='54329', POSTGRES_USER='postgres')
        for s in MANIFEST['services']:
            if 'database' in s:
                key = s['database'].upper()
                password = 'local-' + s['database'].replace('_', '-')
                initial[key + '_DB_PASSWORD'] = password
                initial[key + '_OWNER_PASSWORD'] = password + '-owner'
        command(['bash', str(ROOT / 'infra/foundation/postgres-init.sh')], initial)
        restrict_auth(run)
        command([str(pg / 'pg_ctl'), '-D', str(run / 'data'), '-m', 'fast', '-w', 'stop'])
        child.wait(timeout=10)
        database_entry = next(e for e in ledger['processes'] if e['name'] == 'database')
        if owned(database_entry):
            raise RuntimeError('Bootstrap database session survived shutdown')
        database_entry['finished'] = True
        save(run, ledger)
        child = launch(run, ledger, 'database-restricted', [str(pg / 'postgres'),
                       '-D', str(run / 'data'), '-h', '127.0.0.1', '-p', '54329', '-k', str(run)], env)
        database_ready(pg, run, env, child, cap)
        command([cap['python'], str(ROOT / 'infra/foundation/package-contracts.py'), str(run / 'contracts')])
        for s in services:
            admission(cap)
            if 'database' in s:
                check = ('import importlib.metadata as m; from pathlib import Path; '
                         'rows=Path(__import__("sys").argv[1]).read_text().splitlines(); '
                         'assert all(m.version(r.split("==")[0].split("[")[0]) == r.split("==")[1] '
                         'for r in rows if r and not r.startswith("#"))')
                command([cap['python'], '-c', check, str(ROOT / s['requirements'])])
                command([cap['python'], '-m', 'service_app.migrate'], environment(cap, run, s, True))
                cmd = [cap['python'], '-m', 'uvicorn', s['factory'], '--factory', '--host', '127.0.0.1', '--port', str(s['port']), '--no-access-log']
            else:
                # Resolve dependencies and assets from the existing production build.
                cmd = s['command']
            child = launch(run, ledger, s['name'], cmd, environment(cap, run, s))
            wait_ready(f"http://127.0.0.1:{s['port']}" + ('/health/ready' if 'database' in s else '/api/health'), child, cap)
        ledger['state'] = 'ready'
        save(run, ledger)
        control.close()
        supervise(run, ledger, cap)
    except BaseException:
        if control.closed:
            control = (run / 'control.lock').open('a')
            cleanup_lock(control)
            ledger = json.loads((run / 'ledger.json').read_text())
        stop(run, ledger)
        ledger['state'] = 'failed' if ledger.get('cleanup_complete') else 'cleanup-incomplete'
        save(run, ledger)
        raise
    finally:
        control.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'start', 'status', 'smoke', 'stop'])
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--services', default=','.join(s['name'] for s in MANIFEST['services']))
    parser.add_argument('--capability')
    args = parser.parse_args()
    services = select(args.services)
    if args.command == 'plan':
        print(json.dumps(plan(services), indent=2))
        return
    cap = capability(args.capability) if args.command in ('start', 'smoke') else None
    run = args.run_dir.resolve()
    if args.command == 'start':
        def interrupted(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupted)
        start(run, services, cap)
        return
    run_lock = (run / 'control.lock').open('a')
    fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        ledger = json.loads((run / 'ledger.json').read_text())
        if ledger['schema_version'] != 1:
            raise ValueError('Unsupported ledger')
        if args.command == 'stop':
            stop(run, ledger)
            if not ledger['cleanup_complete']:
                raise RuntimeError('Cleanup remains incomplete')
        elif args.command == 'status':
            print(json.dumps({'state': ledger['state'], 'processes': [dict(e, owned=owned(e)) for e in ledger['processes']]}))
        else:
            if ledger['state'] != 'ready' or not all(owned(e) for e in ledger['processes'] if not e.get('finished')):
                raise RuntimeError('Stack is not owned and ready')
            for s in services:
                admission(cap)
                if s not in ledger['services']:
                    raise ValueError('Service is outside this run')
                with urllib.request.urlopen(f"http://127.0.0.1:{s['port']}" + ('/health/ready' if 'database' in s else '/api/health'), timeout=3) as response:
                    if response.status != 200:
                        raise RuntimeError('Smoke failed')
            print('Smoke passed')
    finally:
        run_lock.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError, TypeError, KeyError):
        print('Native command failed; inspect the private run directory', file=sys.stderr)
        sys.exit(1)
