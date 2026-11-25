"""Consume a private retained backup in an isolated disposable cluster."""
from contextlib import contextmanager
import ctypes
import ctypes.util
import hashlib
import json
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

from native import Unavailable, need, running
from recovery import DOMAINS


@contextmanager
def sql_session(connection, *, expand_database=False):
    """Execute SQL via the single-statement server protocol."""
    library = ctypes.util.find_library('pq')
    need(library, 'restore-measurement-client')
    client = ctypes.CDLL(library)
    pointer = ctypes.c_void_p
    client.PQconnectdbParams.argtypes = [ctypes.POINTER(ctypes.c_char_p),
                                       ctypes.POINTER(ctypes.c_char_p), ctypes.c_int]
    client.PQconnectdbParams.restype = pointer
    client.PQstatus.argtypes = [pointer]
    client.PQexecParams.argtypes = [pointer, ctypes.c_char_p, ctypes.c_int,
                                  pointer, pointer, pointer, pointer, ctypes.c_int]
    client.PQexecParams.restype = pointer
    client.PQresultStatus.argtypes = [pointer]
    client.PQgetvalue.argtypes = [pointer, ctypes.c_int, ctypes.c_int]
    client.PQgetvalue.restype = ctypes.c_char_p
    client.PQclear.argtypes = [pointer]
    client.PQfinish.argtypes = [pointer]
    fields = {'-h': 'host', '-p': 'port', '-U': 'user', '-d': 'dbname'}
    pairs = [(fields[connection[i]], connection[i + 1])
             for i in range(0, len(connection), 2)]
    pairs.append(('connect_timeout', '10'))
    array = ctypes.c_char_p * (len(pairs) + 1)
    handle = client.PQconnectdbParams(array(*(k.encode() for k, _ in pairs), None),
                                    array(*(v.encode() for _, v in pairs), None),
                                    int(expand_database))
    try:
        need(handle and client.PQstatus(handle) == 0, 'restore-measurement-connection')
        def execute(sql, status):
            result = client.PQexecParams(handle, sql.encode(), 0, None, None, None, None, 0)
            try:
                need(result and client.PQresultStatus(result) == status,
                     'restore-measurement-statement')
                if status == 2:
                    raw = client.PQgetvalue(result, 0, 0)
                    need(len(raw) <= 8 * 1024 * 1024, 'bounded-restore-result')
                    return json.loads(raw)
            finally:
                if result:
                    client.PQclear(result)
        yield execute
    finally:
        if handle:
            client.PQfinish(handle)


def measure(connection, query):
    need(isinstance(query, str) and query.strip(), 'restore-measurement-query')
    with sql_session(connection, expand_database=True) as execute:
        execute('BEGIN READ ONLY', 1)
        execute("SET LOCAL statement_timeout = '120s'", 1)
        return execute("SELECT COALESCE(json_agg(row_to_json(measured)), '[]'::json) "
                       'FROM (' + query + ') measured', 2)


def apply_watermarks(socket_dir, database, path):
    sql = path.read_text(encoding='utf-8')
    need(bool(sql.strip()) and '\0' not in sql, 'restore-watermark-statement')
    connection = ['-h', str(socket_dir), '-p', '55439', '-U', 'e09_watermark', '-d', database]
    with sql_session(connection) as execute:
        execute('BEGIN', 1)
        execute("SET LOCAL statement_timeout = '120s'", 1)
        execute(sql, 1)
        execute('COMMIT', 1)


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def contract_digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


WATERMARKS = ('deletions', 'revocations')


class LostAcknowledgedOperations(Unavailable):
    """Carry measured references to the private rehearsal summary."""

    def __init__(self, references):
        super().__init__('lost-acknowledged-operations')
        self.references = sorted(references)


def reviewed_queries(execution):
    reviewed_root, inventory = execution.reviewed_prior
    query_file = 'recovery/domain-reads-v1.json'
    need(query_file in inventory, 'reviewed-domain-reads')
    raw = (reviewed_root / query_file).read_bytes()
    need(hashlib.sha256(raw).hexdigest() == inventory[query_file], 'reviewed-domain-reads')
    queries = json.loads(raw)
    need(set(queries) == set(DOMAINS), 'reviewed-domain-coverage')
    need(all(set(query) == {'operations', 'deletions', 'revocations', 'schema'}
             for query in queries.values()), 'restore-measurement-queries')
    return queries


def watermark_digest(rows):
    return contract_digest(sorted(json.dumps(row, sort_keys=True) for row in rows))


def live_watermarks(execution):
    queries = reviewed_queries(execution)
    return {
        domain: {
            name: watermark_digest(measure(execution.owned_database(domain), queries[domain][name]))
            for name in WATERMARKS
        } for domain in DOMAINS
    }


def live_acknowledged(execution):
    queries = reviewed_queries(execution)
    records = {}
    for domain in DOMAINS:
        rows = measure(execution.owned_database(domain), queries[domain]['operations'])
        need(bool(rows) and all(isinstance(row.get('operation_id'), str)
                                and 0 < len(row['operation_id']) <= 512 for row in rows),
             'live-acknowledged-operations-' + domain)
        records[domain] = rows
    return records


def consume(execution, spec, acknowledged_at_capture):
    need(spec.get('schema_version') == 1, 'E04-connected-backup-output')
    root = Path(spec['root'])
    need(not root.is_symlink() and root.resolve() == execution.run.resolve() / 'e04-backup'
         and root.is_dir() and root.stat().st_mode & 0o077 == 0,
         'private-retained-backup')
    try:
        need(set(acknowledged_at_capture) == set(DOMAINS), 'live-acknowledged-domain-coverage')
        need(spec['source_revision'] and spec['schema_revision']
             and set(spec['domains']) == set(DOMAINS), 'backup-revisions-and-domains')
        domains = spec['domains']
        need(spec['schema_revision'] == contract_digest({
            domain: item['schema_revision'] for domain, item in domains.items()
        }), 'backup-schema-revision')
        backup_reference = contract_digest({
            key: spec[key] for key in ('schema_version', 'source_revision', 'schema_revision', 'domains',
                             'capture_reference', 'watermark_points')
        })
        binaries = Path(execution.settings['postgres_bin'])
        env = {'PATH': str(binaries) + ':/usr/bin:/bin', 'LC_ALL': 'C'}

        def run(binary, *args):
            result = subprocess.run([str(binaries / binary), *args], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=120, check=False)
            need(result.returncode == 0, 'isolated-restore-' + binary)
            need(len(result.stdout) <= 8 * 1024 * 1024, 'bounded-restore-result')
            return result.stdout

        for binary in ('postgres', 'initdb', 'pg_ctl', 'pg_restore', 'psql'):
            need(b' 17.' in run(binary, '--version'), 'restore-postgresql-17')
        queries = reviewed_queries(execution)
        points = spec['watermark_points']
        need(set(points) == {'backup', 'current'} and
             all(set(point) == set(DOMAINS) and
                 all(set(values) == set(WATERMARKS) for values in point.values())
                 for point in points.values()), 'backup-watermark-points')
        for domain, item in spec['domains'].items():
            for field in ('dump', 'watermarks'):
                path = root / item[field]
                need(not Path(item[field]).is_absolute() and '..' not in Path(item[field]).parts
                     and not path.is_symlink() and path.is_file()
                     and path.resolve().is_relative_to(root.resolve()), 'backup-file')
                need(file_digest(path) == item[field + '_sha256'],
                     'backup-file-hash')
            need(set(item['operation_ids']) == {
                row['operation_id'] for row in acknowledged_at_capture[domain]
            } and bool(item['operation_ids']) and bool(item['schema_revision']),
                 'backup-acknowledged-references')
            need('queries' not in item and set(queries[domain]) == {'operations', 'deletions', 'revocations', 'schema'},
                 'restore-measurement-queries')

        restored = []
        lost = set()
        matched_watermarks = set()
        service = 'restore-database'
        signals = {signal.SIGTERM, signal.SIGINT, signal.SIGALRM}
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
        try:
            work = Path(tempfile.mkdtemp(prefix='e09-restore-', dir=execution.run))
            execution.restore_scratch = work
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        try:
            cluster = work / 'cluster'
            child = execution.start_database(
                cluster, binaries, env, service=service, scratch=work)['child']
            local = ['-h', str(work), '-p', '55439', '-U', 'e09_restore']
            deadline = time.monotonic() + 60
            while True:
                need(running(child), 'isolated-restore-postgres')
                probe = subprocess.run(
                    [str(binaries / 'pg_isready'), *local, '-t', '1'], env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                if probe.returncode == 0:
                    break
                need(time.monotonic() < deadline, 'isolated-restore-readiness')
                time.sleep(.1)

            run('psql', '-X', '-v', 'ON_ERROR_STOP=1', *local, '-d', 'postgres',
                '-c', 'CREATE ROLE e09_watermark LOGIN')
            destinations = {}
            acknowledged = {}
            restored_acknowledged = {}
            for index, domain in enumerate(DOMAINS):
                item = spec['domains'][domain]
                database = 'restore_' + str(index)
                run('psql', '-X', '-v', 'ON_ERROR_STOP=1', *local, '-d', 'postgres',
                    '-c', f"CREATE DATABASE {database} ENCODING 'UTF8' TEMPLATE template0")
                destination = [*local, '-d', database]
                run('pg_restore', *destination, '--no-owner', '--no-acl',
                    '--exit-on-error', str(root / item['dump']))
                schema_query = queries[domain]['schema']
                captured_schema = [{'revision': item['schema_revision']}]
                need(measure(destination, schema_query)
                     == measure(execution.owned_database(domain), schema_query)
                     == captured_schema, 'restored-backup-schema-revision-' + domain)
                run('psql', '-X', '-v', 'ON_ERROR_STOP=1', *destination,
                    '-c', 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO e09_watermark')
                for name in WATERMARKS:
                    before = measure(destination, queries[domain][name])
                    need(watermark_digest(before) == points['backup'][domain][name],
                         'restored-backup-watermark-' + name)
                operations = measure(destination, queries[domain]['operations'])
                references = set(item['operation_ids'])
                lost.update(references - {row['operation_id'] for row in operations})
                acknowledged[domain] = watermark_digest(acknowledged_at_capture[domain])
                restored_acknowledged[domain] = watermark_digest(operations)
                destinations[domain] = destination

            if lost:
                raise LostAcknowledgedOperations(lost)
            for domain in DOMAINS:
                need(restored_acknowledged[domain] == acknowledged[domain],
                     'restored-acknowledged-records-' + domain)

            orders, communications = (
                ['-h', str(work), '-p', '55439', '-U', 'e09_watermark', '-d', destinations[domain][-1]]
                for domain in ('orders', 'communications')
            )
            before_replay = execution.verify_restored_orders(orders, communications)
            for domain, destination in destinations.items():
                item = domains[domain]
                run('psql', '-X', '-v', 'ON_ERROR_STOP=1', *destination,
                    '-c', 'GRANT INSERT, UPDATE, DELETE ON ALL TABLES '
                          'IN SCHEMA public TO e09_watermark; '
                          'GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO e09_watermark')
                apply_watermarks(work, destination[-1], root / item['watermarks'])
                current = execution.owned_database(domain)
                for name, query in queries[domain].items():
                    actual = measure(destination, query)
                    if name == 'operations':
                        references = set(item['operation_ids'])
                        retained = [row for row in actual if row['operation_id'] in references]
                        missing = references - {row['operation_id'] for row in retained}
                        if missing:
                            raise LostAcknowledgedOperations(missing)
                        need(watermark_digest(retained) == acknowledged[domain],
                             'watermark-replay-changed-acknowledged-operations')
                    expected = measure(current, query)
                    if name in {'operations', 'schema'}:
                        need(bool(expected), 'current-restore-' + name)
                    need(watermark_digest(actual) == watermark_digest(expected),
                         'measured-restore-' + name)
                    if name in WATERMARKS:
                        need(watermark_digest(actual) == points['current'][domain][name],
                             'restored-current-watermark-' + name)
                        if expected and points['backup'][domain][name] != points['current'][domain][name]:
                            matched_watermarks.add(name)
                    if name == 'schema':
                        need(actual == [{'revision': item['schema_revision']}], 'restored-schema-revision')
                restored.append(domain)
            restored_orders = execution.verify_restored_orders(orders, communications)
            need(restored_orders == before_replay, 'watermark-replay-changed-payment-records')
        except LostAcknowledgedOperations as error:
            execution.partial_measurements['lost_acknowledged_operations'] = error.references
            raise
        finally:
            execution.stop(service)
            shutil.rmtree(work)
            execution.restore_scratch = None
        for name in ('deletions', 'revocations'):
            need(name in matched_watermarks, 'current-restore-' + name)
        return dict(**restored_orders, backup_provider='E04', backup_reference=backup_reference,
                    isolated=True, postgres_major=17, restored_domains=restored,
                    lost_acknowledged_operations=sorted(lost), current_deletions_applied='deletions' in matched_watermarks,
                    current_revocations_applied='revocations' in matched_watermarks)
    finally:
        shutil.rmtree(root)
