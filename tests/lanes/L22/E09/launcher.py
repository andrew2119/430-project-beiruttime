"""Own the private database and release recovery lifetime."""
from http.client import HTTPException
import json
from pathlib import Path
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit

from native import ROOT, Execution, Unavailable, need, running
from recovery import DOMAINS
from restore import consume, contract_digest, file_digest, live_acknowledged, live_watermarks


BACKUP_PRODUCER = ROOT / 'tests/lanes/L24/E04/retained.py'

RUNTIME_ROLE_CHECK = """
SELECT 1
FROM pg_catalog.pg_roles AS runtime
WHERE runtime.rolname = :'runtime_role'
  AND runtime.rolcanlogin
  AND NOT (runtime.rolsuper OR runtime.rolcreatedb OR runtime.rolcreaterole
           OR runtime.rolreplication OR runtime.rolbypassrls)
  AND NOT EXISTS (
      SELECT FROM pg_catalog.pg_auth_members WHERE member = runtime.oid
  )
  AND NOT EXISTS (
      SELECT FROM pg_catalog.pg_shdepend
      WHERE refclassid = 'pg_catalog.pg_authid'::regclass
        AND refobjid = runtime.oid AND deptype = 'o'
  )
  AND has_database_privilege(runtime.oid, current_database(), 'CONNECT')
  AND NOT has_database_privilege(runtime.oid, current_database(), 'CREATE,TEMP')
  AND NOT EXISTS (
      SELECT FROM pg_catalog.pg_database AS db
      WHERE db.datname <> current_database() AND db.datallowconn
        AND has_database_privilege(runtime.oid, db.oid, 'CONNECT')
  )
  AND NOT EXISTS (
      SELECT FROM pg_catalog.pg_namespace AS ns
      WHERE has_schema_privilege(runtime.oid, ns.oid, 'CREATE')
  );
"""

EMPTY_DATABASE_CHECK = r"""
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SELECT format('SELECT 1 FROM %I.%I LIMIT 1', n.nspname, c.relname)
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm', 'f')
  AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
  AND NOT (n.nspname = 'public' AND c.relname::text IN ('migration_ledger', :'dictionary'))
\gexec
ROLLBACK;
"""


class WholeStack(Execution):
    def start(self):
        self.isolated()
        config = self.settings.get('e09_database', {})
        need(config.get('schema_version') == 1, 'private-database-input')
        cluster = self.run / 'e09-database'
        need(not cluster.exists() and not cluster.is_symlink(), 'fresh-private-database')
        bootstrap = Path(config.get('bootstrap_sql', '')).resolve()
        need(bootstrap.is_relative_to(self.run.resolve()) and bootstrap.is_file()
             and not bootstrap.is_symlink()
             and bootstrap.stat().st_mode & 0o077 == 0, 'private-database-bootstrap')
        authentication = Path(config.get('authentication_file', '')).resolve()
        need(authentication.is_relative_to(self.run.resolve()) and authentication.is_file()
             and authentication.stat().st_mode & 0o077 == 0, 'private-database-authentication')
        rules = authentication.read_text().splitlines()
        need(bool(rules) and all(not line.strip() or line.lstrip().startswith('#')
             or (len(line.split()) == 5 and line.split()[0] == 'host'
                 and line.split()[3] in {'127.0.0.1/32', '::1/128'}
                 and line.split()[4] == 'scram-sha-256') for line in rules),
             'restricted-database-authentication')
        binaries = Path(self.settings['postgres_bin'])
        env = {'PATH': str(binaries) + ':/usr/bin:/bin', 'LC_ALL': 'C'}
        version = subprocess.run([str(binaries / 'postgres'), '--version'],
                                 env=env, capture_output=True, check=True, timeout=10)
        need(b' 17.' in version.stdout, 'private-postgresql-17')
        signals = {signal.SIGTERM, signal.SIGINT, signal.SIGALRM}
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
        try:
            try:
                cluster.mkdir(mode=0o700)
            except FileExistsError:
                raise Unavailable('fresh-private-database') from None
            self.database_owned = True
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        try:
            child = self.start_database(cluster, binaries, env)['child']
            until = time.monotonic() + 60
            while True:
                need(running(child), 'private-database-exited')
                result = subprocess.run([str(binaries / 'pg_isready'), '-h', str(self.database_socket),
                                         '-p', '54329'], env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        timeout=2)
                if result.returncode == 0:
                    break
                need(time.monotonic() < until, 'private-database-readiness')
                time.sleep(.1)
            self.command([str(binaries / 'psql'), '-X', '-v', 'ON_ERROR_STOP=1',
                          '-h', str(self.database_socket), '-p', '54329', '-U', 'e09_owner',
                          '-d', 'postgres', '-f', str(bootstrap)], self.run, env)
            self.verify_runtime_databases(binaries, env)
            self.seal_database(cluster, binaries, env, rules)
            super().start()
        except BaseException:
            self.close()
            raise

    def call(self, action, request):
        if action == 'authoritative-reads' and 'candidate' not in request:
            from driver import Interrupted
            from observations import acknowledged_payments

            try:
                self.prepare_products()
            except (Interrupted, HTTPException, ValueError, KeyError, TypeError, OSError,
                    subprocess.SubprocessError):
                try:
                    self.acknowledged_baseline_ids.update(
                        acknowledged_payments(self.owned_database('orders')))
                except (ValueError, KeyError, TypeError, OSError):
                    pass  # Preserve the original journey failure.
                raise
            self.acknowledged_baseline_ids.update(
                acknowledged_payments(self.owned_database('orders')))
        return super().call(action, request)

    def verify_runtime_databases(self, binaries, env):
        roles = set()
        databases = set()
        for domain in DOMAINS:
            runtime = self.environment(domain, ROOT)['BT_DATABASE_URL']
            address = urlsplit(runtime)
            database = unquote(address.path.removeprefix('/'))
            role = unquote(address.username)
            need(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_-]{0,62}', database),
                 domain + '-provisioned-database')
            need(role not in roles and database not in databases, domain + '-runtime-scope')
            roles.add(role)
            databases.add(database)
            dictionary = 'catalog_discovery_aliases_v1' if domain == 'catalog' else ''
            argv = [str(binaries / 'psql'), '-XqAtw', '-v', 'ON_ERROR_STOP=1',
                    '-h', str(self.database_socket), '-p', '54329', '-U', 'e09_owner',
                    '-d', database]
            try:
                privileges = subprocess.run(
                    [*argv, '-v', 'runtime_role=' + role],
                    input=RUNTIME_ROLE_CHECK.encode(), env=env, capture_output=True, timeout=30)
                need(privileges.returncode == 0 and privileges.stdout.strip() == b'1',
                     domain + '-restricted-runtime-role')
                result = subprocess.run(
                    [*argv, '-v', 'dictionary=' + dictionary],
                    input=EMPTY_DATABASE_CHECK.encode(), env=env, capture_output=True, timeout=30)
            except subprocess.TimeoutExpired:
                raise Unavailable(domain + '-provisioned-database-timeout') from None
            need(result.returncode == 0, domain + '-provisioned-database-check')
            need(not result.stdout.strip(), domain + '-provisioned-business-records')

    def start_database(self, cluster, binaries, env, *, service='database', scratch=None):
        # Gate initialization and startup on ownership of the PID namespace.
        if scratch is None:
            socket_dir = self.run / 'e09-database-socket'
            socket_dir.mkdir(mode=0o700)
            self.database_socket = socket_dir
            mounts = [cluster, socket_dir]
            host, port, owner = '127.0.0.1', '54329', 'e09_owner'
        else:
            socket_dir = scratch
            mounts = [scratch]
            host, port, owner = '', '55439', 'e09_restore'
        binds = [argument for path in mounts for argument in ('--bind', str(path), str(path))]
        reader, writer = os.pipe()
        with os.fdopen(reader, 'rb') as gate, os.fdopen(writer, 'wb') as permit, \
                tempfile.TemporaryFile(dir=self.run) as info:
            initialize = (
                'set -eu\n'
                'read -r start\n'
                'bin=$1\ncluster=$2\nowner=$3\nshift 3\n'
                '"$bin/initdb" -D "$cluster" --username="$owner" '
                '--auth-local=trust --auth-host=reject --encoding=UTF8 --no-locale </dev/null\n'
                'exec "$bin/postgres" -D "$cluster" "$@" </dev/null'
            )
            argv = [*self.application_namespace(), '--info-fd', str(info.fileno()),
                    '--tmpfs', '/dev/shm', *binds, '--chdir', '/',
                    '--', '/bin/sh', '-c', initialize, 'e09',
                    str(binaries), str(cluster), owner, '-h', host,
                    '-p', port, '-k', str(socket_dir)]
            entry = self.spawn(service, argv, self.run, env, stdin=gate,
                               pass_fds=(info.fileno(),))
            gate.close()
            deadline = time.monotonic() + 10
            while True:
                raw = os.pread(info.fileno(), 4096, 0)
                try:
                    pid = json.loads(raw)['child-pid']
                    break
                except json.JSONDecodeError:
                    need(running(entry['child']) and time.monotonic() < deadline,
                         'owned-database-namespace')
                    time.sleep(.05)
            need(pid != entry['child'].pid and os.getsid(pid) == entry['session'],
                 'owned-database-namespace')
            signals = {signal.SIGTERM, signal.SIGINT, signal.SIGALRM}
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
            try:
                entry['namespace_fd'] = os.pidfd_open(pid)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            permit.write(b'start\n')
            permit.flush()
            return entry

    def stop(self, service):
        entry = self.children.get(service)
        namespace = entry.get('namespace_fd') if entry else None
        if namespace is not None:
            # The namespace init exits only after its remaining processes die.
            try:
                signal.pidfd_send_signal(namespace, signal.SIGKILL)
            except ProcessLookupError:
                pass
            poll = select.poll()
            poll.register(namespace, select.POLLIN)
            need(any(events & select.POLLIN for _, events in poll.poll(15000)),
                 'owned-database-namespace-stop')
        try:
            super().stop(service)
        finally:
            if namespace is not None and service not in self.children:
                os.close(namespace)

    def seal_database(self, cluster, binaries, env, rules):
        (cluster / 'pg_hba.conf').write_text(
            'local all all reject\n'
            'host all e09_owner 127.0.0.1/32 reject\n'
            'host all e09_owner ::1/128 reject\n' + '\n'.join(rules) + '\n')
        reload = subprocess.run(
            [str(binaries / 'psql'), '-XAt', '-v', 'ON_ERROR_STOP=1',
             '-h', str(self.database_socket), '-p', '54329', '-U', 'e09_owner',
             '-d', 'postgres', '-c', 'SELECT pg_reload_conf()'],
            env=env, capture_output=True, timeout=10)
        need(reload.returncode == 0 and reload.stdout.strip() == b't',
             'private-database-authentication-reload')
        # Wait for a new connection to observe rejection, rather than a queued reload.
        until = time.monotonic() + 10
        while True:
            probe = subprocess.run(
                [str(binaries / 'psql'), '-X', '-w', '-h', str(self.database_socket),
                 '-p', '54329', '-U', 'e09_owner', '-d', 'postgres', '-c', 'SELECT 1'],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=2)
            if probe.returncode and b'pg_hba.conf rejects connection' in probe.stderr:
                return
            need(time.monotonic() < until, 'provisioning-access-revoked')
            time.sleep(.05)

    def verify_restored_orders(self, connection, communications):
        from observations import read_orders

        restored = read_orders(connection, communications)
        need(restored == self.reads(), 'restored-orders-product-records')
        return restored

    def restore(self, request):
        self.isolated()
        need('database' in self.children and running(self.children['database']['child']),
             'owned-backup-source')
        references = request.get('acknowledged_product_ids', [])
        need(bool(references) and all(isinstance(ref, str) and 0 < len(ref) <= 512
                                     for ref in references), 'backup-acknowledged-references')
        need(BACKUP_PRODUCER.is_file(), 'E04-connected-backup-output')
        root = self.run / 'e04-backup'
        signals = {signal.SIGTERM, signal.SIGINT, signal.SIGALRM}
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
        try:
            need(not root.exists() and not root.is_symlink(), 'fresh-private-backup')
            root.mkdir(mode=0o700)
            self.backup_root = root
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        try:
            acknowledged = live_acknowledged(self)
            required_ids = {domain: sorted({row['operation_id'] for row in rows})
                            for domain, rows in acknowledged.items()}
            need(set(references).issubset(required_ids['orders']),
                 'backup-acknowledged-references')
            common = {'schema_version': 1, 'source_revision': request['source_revision'],
                      'required_operation_ids': required_ids}
            backup = live_watermarks(self)
            capture = self.backup_phase(root, 'capture.json', {
                **common, 'phase': 'capture', 'backup_watermarks': backup})
            need(live_watermarks(self) == backup, 'stable-backup-watermark-point')
            need(capture.get('backup_watermarks') == backup, 'backup-watermark-point')
            dumps = self.retained_dumps(root, capture)
            for domain in DOMAINS:
                need(set(capture['domains'][domain]['operation_ids']) == set(required_ids[domain]),
                     'backup-acknowledged-references')
            self.prepare_products('e09_watermark_journey')
            current = live_watermarks(self)
            for name in ('deletions', 'revocations'):
                need(any(backup[domain][name] != current[domain][name] for domain in DOMAINS),
                     'product-watermark-transition-' + name)
            handoff = self.backup_phase(root, 'handoff.json', {
                **common, 'phase': 'finalize', 'capture_reference': contract_digest(capture),
                'current_watermarks': current})
            need(handoff.get('capture_reference') == contract_digest(capture)
                 and handoff.get('watermark_points') == {'backup': backup, 'current': current}
                 and self.retained_dumps(root, handoff) == dumps,
                 'retained-backup-point-binding')
            return consume(self, handoff, acknowledged)
        finally:
            if root.exists():
                shutil.rmtree(root)
            self.backup_root = None

    def retained_dumps(self, root, descriptor):
        need(set(descriptor['domains']) == set(DOMAINS), 'backup-revisions-and-domains')
        dumps = {}
        paths = set()
        for domain, item in descriptor['domains'].items():
            relative = Path(item['dump'])
            path = root / relative
            need(not relative.is_absolute() and '..' not in relative.parts
                 and not path.is_symlink() and path.is_file()
                 and path.resolve().is_relative_to(root.resolve()), 'backup-file')
            resolved = path.resolve()
            need(resolved not in paths, 'distinct-domain-backup-files')
            paths.add(resolved)
            operations = item['operation_ids']
            need(isinstance(operations, list) and bool(operations)
                 and all(isinstance(ref, str) and 0 < len(ref) <= 512 for ref in operations)
                 and len(set(operations)) == len(operations), 'backup-acknowledged-references')
            digest = file_digest(path)
            need(digest == item['dump_sha256'], 'backup-file-hash')
            dumps[domain] = (item['dump'], digest, item['schema_revision'],
                             item['operation_ids'])
        return dumps

    def backup_phase(self, root, filename, payload):
        descriptor = root / filename
        argv = [self.settings.get('python', sys.executable), str(BACKUP_PRODUCER),
                '--run-dir', str(self.run), '--output-dir', str(root)]
        env = {'PATH': self.settings['postgres_bin'] + ':/usr/bin:/bin',
               'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}
        with tempfile.TemporaryFile(dir=self.run) as stdin:
            stdin.write(json.dumps(payload).encode())
            stdin.seek(0)
            child = self.spawn('backup-producer', argv, self.run, env, stdin=stdin)['child']
            try:
                deadline = time.monotonic() + 300
                while running(child):
                    need(time.monotonic() < deadline, 'E04-connected-backup-timeout')
                    time.sleep(.1)
            finally:
                self.stop('backup-producer')
        need(child.returncode == 0 and not descriptor.is_symlink() and descriptor.is_file(),
             'E04-connected-backup-output')
        with descriptor.open('rb') as stream:
            need(stat.S_IMODE(os.fstat(stream.fileno()).st_mode) == 0o600,
                 'private-backup-descriptor')
            raw = stream.read(8 * 1024 * 1024 + 1)
        need(len(raw) <= 8 * 1024 * 1024, 'bounded-backup-descriptor')
        handoff = json.loads(raw)
        need(handoff.get('schema_version') == 1 and Path(handoff['root']) == root
             and handoff['source_revision'] == payload['source_revision'],
             'current-backup-source')
        return handoff

    def close(self):
        try:
            super().close()
        finally:
            if not self.children and getattr(self, 'database_owned', False):
                for path in (self.run / 'e09-database', getattr(self, 'database_socket', None)):
                    if path is None:
                        continue
                    try:
                        shutil.rmtree(path)
                    except FileNotFoundError:
                        if path.exists() or path.is_symlink():
                            raise
                self.database_owned = False
            scratch = getattr(self, 'restore_scratch', None)
            if scratch is not None and 'restore-database' not in self.children:
                shutil.rmtree(scratch)
                self.restore_scratch = None
            root = getattr(self, 'backup_root', None)
            if root is not None and root.exists():
                shutil.rmtree(root)


if __name__ == '__main__':
    from driver import main
    raise SystemExit(main(whole_stack=True))
