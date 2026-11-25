"""Private, local PostgreSQL restore exercise. No serving or payment commands."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import secrets
import stat
import subprocess
import time
from urllib.parse import unquote, urlsplit

from byte_backup import ByteBackupError, export_bytes, metadata, restore_bytes
from current_authority import check_unaffected, reconcile_identity
from handoff import publish, workspace
from fixtures import DOMAINS
from privacy_watermarks import check_current, from_rows
from restore import CONTRACT, digest
from producer_reads import PRODUCER_READS, ProvenanceError, validate_provenance
from recovery_cases import recovery_cases
from recovery_runtime import open_runtime

ROOT = Path(__file__).resolve().parents[4]
INVARIANTS = {
    'I07': ('deletion_preserved', 'revocation_preserved', 'retention_preserved'),
    'O08': ('principal_preserved', 'fees_excluded', 'journal_balanced'),
    'S11': ('actual_receipt_preserved', 'current_checks_preserved', 'custody_preserved'),
    'A10': ('dispute_hold_preserved', 'release_authority_preserved', 'totals_preserved'),
}
# Only reviewed, versioned producer reads belong here. Run input cannot add reads.
# Each entry must check durable operation provenance as well as current facts.


CASES = ('nine_database_restore', 'migration', 'I07', 'O08', 'S11', 'A10', 'file_store')


class CapabilityError(RuntimeError):
    pass


def execute(command, env=None):
    result = subprocess.run(command, env=env, capture_output=True, timeout=300)
    if result.returncode:
        raise CapabilityError('local_command_failed:' + Path(command[0]).name)
    return result.stdout.decode().strip()


def database_plan(url, executable, *arguments):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('postgresql', 'postgres') or parsed.hostname != '127.0.0.1'
            or parsed.port != 54329 or parsed.query or parsed.fragment
            or not parsed.username or not parsed.password or not parsed.path.strip('/')):
        raise CapabilityError('local_owner_database_url')
    env = {k: os.environ[k] for k in ('PATH', 'LANG') if k in os.environ}
    env['PGPASSWORD'] = unquote(parsed.password)
    command = [executable, '--host=127.0.0.1', '--port=54329',
               '--username=' + unquote(parsed.username), '--dbname=' + unquote(parsed.path[1:]),
               *arguments]
    return command, env


def private_json(path):
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise CapabilityError('private_configuration_0600')
    return json.loads(path.read_text())


def producer_read(specification, name):
    registered = PRODUCER_READS.get(name)
    if registered is None:
        raise CapabilityError('verified_producer_read_unavailable:' + name)
    if ('sql' in specification or specification.get('query_id') != registered['query_id']
            or specification.get('domain') != registered['domain']):
        raise CapabilityError('unverified_producer_read:' + name)
    validated_operation_ids(specification, name)
    return registered['sql']


def validated_operation_ids(specification, name):
    operations = specification.get('operation_ids')
    if (not isinstance(operations, list) or not operations or len(operations) > 10
            or any(not isinstance(value, str) or not value.strip() for value in operations)
            or len(set(operations)) != len(operations)):
        raise CapabilityError('connected_operation_inputs:' + name)
    return list(operations)


def summary_operation_ids(run):
    inputs = private_json(run / 'e04-inputs.json')
    if inputs.get('origin') != 'connected' or inputs.get('schema_version') != 1:
        raise CapabilityError('connected_producer_inputs')
    result = {}
    for name in (*INVARIANTS, 'file_store'):
        specification = (inputs.get('file_store') if name == 'file_store'
                         else inputs.get('probes', {}).get(name))
        if not isinstance(specification, dict):
            continue
        try:
            result[name] = validated_operation_ids(specification, name)
        except CapabilityError:
            continue
    operations = list(dict.fromkeys(value for values in result.values() for value in values))
    result['nine_database_restore'] = list(operations)
    result['migration'] = list(operations)
    return result


async def prepare_private_roles(connection):
    # The migration runner derives this role from the private owner name.
    await connection.execute('CREATE ROLE e04 NOLOGIN')


def load_inputs(run):
    native = private_json(run / 'native-v1.json')
    if native.get('schema_version') != 1:
        raise CapabilityError('native_schema_version')
    urls = {}
    for domain in DOMAINS:
        settings = native['services'][domain]['env']
        url = settings.get('BT_MIGRATION_DATABASE_URL') or settings.get('BT_DATABASE_OWNER_URL')
        if not url:
            raise CapabilityError('owner_credentials:' + domain)
        database_plan(url, 'pg_dump')
        urls[domain] = url
    if len({urlsplit(url).path for url in urls.values()}) != 9:
        raise CapabilityError('nine_distinct_databases')
    inputs = private_json(run / 'e04-inputs.json')
    if inputs.get('origin') != 'connected' or inputs.get('schema_version') != 1:
        raise CapabilityError('connected_producer_inputs')
    for name in INVARIANTS:
        producer_read(inputs['probes'][name], name)
    producer_read(inputs['file_store'], 'file_store')
    return urls, inputs


def quote(value):
    return '"' + value.replace('"', '""') + '"'


async def inventory(connection):
    tables = await connection.fetch("SELECT schemaname, tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2")
    result = {}
    for table in tables:
        identifier = quote(table['schemaname']) + '.' + quote(table['tablename'])
        # Canonical rows preserve duplicate multiplicity without exposing private values.
        rows = await connection.fetch('SELECT to_jsonb(t)::text AS body FROM ' + identifier + ' t ORDER BY to_jsonb(t)::text COLLATE "C"')
        checksum = hashlib.sha256()
        for row in rows:
            body = row['body'].encode()
            checksum.update(len(body).to_bytes(8, 'big') + body)
        result[identifier] = {'rows': len(rows), 'sha256': checksum.hexdigest()}
    if not result or not any('migration_ledger' in name for name in result):
        raise CapabilityError('populated_migrated_database')
    return result


def verify_saved_inventory(before, restored, domain):
    # Privacy reconciliation cannot repair a damaged backup into passing proof.
    if restored != before:
        raise CapabilityError('restored_rows_mismatch:' + domain)


async def probe(connection, specification, name):
    # Read-only transactions prohibit producer queries from creating results.
    async with connection.transaction(readonly=True):
        rows = await connection.fetch(producer_read(specification, name), specification['operation_ids'])
    try:
        validate_provenance([dict(row) for row in rows], specification['operation_ids'], name)
    except ProvenanceError as failure:
        raise CapabilityError(str(failure)) from None
    if (len(rows) != len(specification['operation_ids'])
            or {row['operation_id'] for row in rows} != set(specification['operation_ids'])
            or any(row['passed'] is not True or any(row[field] is not True for field in INVARIANTS[name])
                   for row in rows)):
        raise CapabilityError('producer_invariant_failed')
    return sorted([dict(row) for row in rows], key=lambda row: row['operation_id'])


async def migration(connection, url, domain):
    from bt_runtime.app import db
    from unittest.mock import patch

    modules = ROOT / 'services' / domain / 'modules'
    before = await inventory(connection)
    steps = db.migration_steps(modules)
    # Real transactional DDL and ledger rollback, followed by retry and duplicate.
    extra = ('L24.e04/restore-check', 'e' * 64, 'CREATE TABLE e04_restore_check (id integer)')
    with patch.object(db, 'migration_steps', return_value=steps + [extra, ('L24.e04/failure', 'f' * 64, 'SELECT 1/0')]):
        try:
            await db.migrate(url, modules)
        except Exception:
            pass
        else:
            raise CapabilityError('migration_failure_not_rolled_back')
    if await inventory(connection) != before:
        raise CapabilityError('migration_rollback_changed_data')
    with patch.object(db, 'migration_steps', return_value=steps + [extra]):
        await db.migrate(url, modules)
        first = await inventory(connection)
        await db.migrate(url, modules)
        if await inventory(connection) != first:
            raise CapabilityError('migration_duplicate_changed_data')
    for rejected in (steps + [(extra[0], 'd' * 64, extra[2])], steps):
        with patch.object(db, 'migration_steps', return_value=rejected):
            try:
                await db.migrate(url, modules)
            except RuntimeError:
                pass
            else:
                raise CapabilityError('migration_history_not_rejected')
    await connection.execute('DROP TABLE e04_restore_check')
    await connection.execute('DELETE FROM migration_ledger WHERE step_id=$1', extra[0])
    if await inventory(connection) != before:
        raise CapabilityError('migration_changed_domain_data')


def files_restore(specification, target):
    source = Path(specification['root'])
    rows = specification['files']
    if not rows or len(rows) > CONTRACT['limits']['files']:
        raise CapabilityError('actual_file_metadata')
    target.mkdir(mode=0o700)
    for row in rows:
        name = row['file_id']
        if source.is_symlink() or not source.is_dir():
            raise CapabilityError('actual_file_root')
        if not name or Path(name).name != name or name in ('.', '..'):
            raise CapabilityError('opaque_file_id')
        if row['tombstoned']:
            continue
        path = source / name
        if (path.is_symlink() or not path.is_file()
                or path.stat().st_size > CONTRACT['limits']['file_bytes']):
            raise CapabilityError('actual_file_unavailable')
        content = path.read_bytes()
        if len(content) != row['size'] or digest(content) != row['checksum']:
            raise CapabilityError('actual_file_integrity')
        (target / name).write_bytes(content)
        if (target / name).read_bytes() != content:
            raise CapabilityError('restored_file_integrity')
    if {p.name for p in target.iterdir()} != {r['file_id'] for r in rows if not r['tombstoned']}:
        raise CapabilityError('restored_tombstones')


def checked_file_rows(rows, specification):
    rows = [dict(row) for row in rows]
    try:
        metadata(rows)
    except ByteBackupError as failure:
        raise CapabilityError(str(failure)) from None
    requested = validated_operation_ids(specification, 'file_store')
    try:
        validate_provenance(rows, requested, 'file_store')
    except ProvenanceError as failure:
        raise CapabilityError(str(failure)) from None
    if (len(rows) != len(requested)
            or {row['operation_id'] for row in rows} != set(requested)):
        raise CapabilityError('file_operation_provenance')
    return rows


def export_producer_bytes(rows, specification, target):
    try:
        return export_bytes(checked_file_rows(rows, specification), target)
    except ByteBackupError as failure:
        raise CapabilityError(str(failure)) from None


def restore_producer_bytes(manifest, rows, specification, source, target):
    try:
        return restore_bytes(manifest, checked_file_rows(rows, specification), source, target)
    except ByteBackupError as failure:
        raise CapabilityError(str(failure)) from None


async def connected(run, port, record, backup=None, retain=None, recovery_provider=None):
    import asyncpg
    urls, inputs = load_inputs(run)
    for binary in ('initdb', 'pg_ctl', 'pg_dump', 'pg_restore'):
        if not shutil.which(binary) or ' 17.' not in execute([binary, '--version']):
            raise CapabilityError('postgresql_17:' + binary)
    operations = summary_operation_ids(run)
    recovered_operations = set()
    with workspace(run, backup, record['source_revision'], operations) as (work, saved):
        cluster = work / 'cluster'
        password = secrets.token_hex(24)
        password_file = work / 'password'
        password_file.write_text(password)
        password_file.chmod(0o600)
        private_env = {k: os.environ[k] for k in ('PATH', 'LANG') if k in os.environ}
        private_env['PGPASSWORD'] = password
        execute(['initdb', '-D', str(cluster), '--auth-local=trust',
                 '--auth-host=scram-sha-256', '--pwfile=' + str(password_file),
                 '--username=e04_owner', '--no-locale'])
        started = False
        try:
            execute(['pg_ctl', '-D', str(cluster), '-l', str(work / 'server.log'), '-w', 'start', '-o',
                     f'-h 127.0.0.1 -p {port} -k {work}'])
            started = True
            admin = await asyncpg.connect(host='127.0.0.1', port=port, user='e04_owner', password=password, database='postgres')
            try:
                await prepare_private_roles(admin)
                for index, domain in enumerate(DOMAINS):
                    source = await asyncpg.connect(urls[domain])
                    destination = None
                    try:
                        if not 170000 <= int(await source.fetchval('SHOW server_version_num')) < 180000:
                            raise CapabilityError('source_postgresql_17')
                        if saved is None:
                            async with source.transaction(isolation='repeatable_read', readonly=True):
                                snapshot = await source.fetchval('SELECT pg_export_snapshot()')
                                before = await inventory(source)
                                expected = {}
                                for name, spec in inputs['probes'].items():
                                    if spec['domain'] == domain:
                                        expected[name] = await probe(source, spec, name)
                                dump = work / (domain + '.dump')
                                command, env = database_plan(urls[domain], 'pg_dump', '--format=custom', '--no-owner', '--no-acl', '--snapshot=' + snapshot, '--file=' + str(dump))
                                await asyncio.to_thread(execute, command, env)
                        else:
                            before = saved['domains'][domain]['inventory']
                            current_inventory = await inventory(source)
                            current_schema = {name: value for name, value in current_inventory.items()
                                              if 'migration_ledger' in name}
                            if current_schema != saved['domains'][domain]['schema_revision']:
                                raise CapabilityError('backup_schema_revision_mismatch')
                            dump = backup / (domain + '.dump')
                            expected = {name: await probe(source, spec, name)
                                        for name, spec in inputs['probes'].items()
                                        if spec['domain'] == domain}
                        database = 'e04_' + str(index)
                        await admin.execute('CREATE DATABASE ' + quote(database))
                        await asyncio.to_thread(execute, ['pg_restore', '--host=127.0.0.1', '--port=' + str(port), '--username=e04_owner', '--dbname=' + database, '--no-owner', '--no-acl', '--exit-on-error', str(dump)], private_env)
                        private_url = f'postgresql://e04_owner:{password}@127.0.0.1:{port}/{database}'
                        destination = await asyncpg.connect(private_url)
                        verify_saved_inventory(before, await inventory(destination), domain)
                        if domain == 'identity':
                            # Read revisions and authority from one current source snapshot.
                            async with source.transaction(isolation='repeatable_read', readonly=True):
                                expected = {name: await probe(source, spec, name)
                                            for name, spec in inputs['probes'].items()
                                            if spec['domain'] == domain}
                                watermarks = from_rows(expected.get('I07', []), operations)
                                if saved is not None:
                                    check_current(saved['privacy_watermarks'], watermarks, operations)
                                authority = await reconcile_identity(source, destination)
                            check_unaffected(before, await inventory(destination))
                            record['identity_authority'] = authority
                            record['privacy_watermarks'] = watermarks
                        for name, expected_rows in expected.items():
                            restored_rows = await probe(destination, inputs['probes'][name], name)
                            if restored_rows != expected_rows:
                                raise CapabilityError('restored_invariant_mismatch:' + name)
                            recovered_operations.update(row['operation_id'] for row in restored_rows)
                        await migration(destination, private_url, domain)
                        record['databases'][domain] = before
                    finally:
                        await source.close()
                        if destination:
                            await destination.close()
                file_spec = inputs['file_store']
                current = await asyncpg.connect(urls[file_spec['domain']])
                try:
                    if saved is None:
                        async with current.transaction(isolation='repeatable_read', readonly=True):
                            rows = await current.fetch(producer_read(file_spec, 'file_store'), file_spec['operation_ids'])
                            manifest = export_producer_bytes(rows, file_spec, work / 'backup-files')
                    else:
                        manifest = saved['files']
                    # Fresh authority is intentionally outside the backup snapshot.
                    async with current.transaction(isolation='repeatable_read', readonly=True):
                        rows = await current.fetch(producer_read(file_spec, 'file_store'),
                                                   file_spec['operation_ids'])
                        file_result = restore_producer_bytes(
                            manifest, rows, file_spec,
                            (backup if saved else work) / 'backup-files', work / 'restored-files')
                        recovered_operations.update(row['operation_id'] for row in rows)
                        record['file_authority'] = file_result
                    record['restored_domains'] = len(record['databases'])
                    acknowledged = {value for values in operations.values() for value in values}
                    record['lost_acknowledged_operations'] = sorted(acknowledged - recovered_operations)
                    if record['lost_acknowledged_operations']:
                        raise CapabilityError('lost_acknowledged_operations')
                    record['current_authority_applied'] = 'identity_authority' in record
                    record['recovery_cases'] = await recovery_cases(recovery_provider, operations)
                    if retain is not None:
                        publish(retain, work, record, operations, manifest)
                finally:
                    await current.close()
            finally:
                await admin.close()
        finally:
            if started:
                execute(['pg_ctl', '-D', str(cluster), '-m', 'immediate', '-w', 'stop'])


async def invoke(run, port, record, backup=None, retain=None, runtime=None):
    if runtime is None:
        await connected(run, port, record, backup, retain)
        return
    async with open_runtime(runtime, run, summary_operation_ids(run)) as provider:
        await connected(run, port, record, backup, retain, recovery_provider=provider)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--restore-port', type=int, default=55439)
    parser.add_argument('--recovery-runtime', metavar='MODULE:FACTORY',
                        help='installed owning recovery runtime context factory')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--retain-backup', type=Path)
    mode.add_argument('--consume-backup', type=Path)
    args = parser.parse_args(argv)
    if not 1024 <= args.restore_port <= 65535 or args.restore_port in (54329, 3000, *range(8101, 8110)):
        parser.error('a separate private restore port is required')
    run = args.run_dir.resolve()
    if run == ROOT or ROOT in run.parents:
        parser.error('run directory must be outside the checkout')
    for artifact in (args.retain_backup, args.consume_backup):
        if artifact is not None and (artifact.resolve() == ROOT or ROOT in artifact.resolve().parents):
            parser.error('backup directory must be outside the checkout')
    output = run / 'scenarios' / 'e04'
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    revision = execute(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'])
    record = {'schema_version': 1, 'source_revision': revision, 'connected': False, 'databases': {}}
    start = time.monotonic()
    error = None
    try:
        asyncio.run(invoke(run, args.restore_port, record,
                           args.consume_backup, args.retain_backup, args.recovery_runtime))
    except CapabilityError as failure:
        error = str(failure)
    except Exception as failure:
        # Driver errors can contain credentials or row values; retain only the category.
        error = 'missing_or_failed_capability:' + type(failure).__name__
    elapsed = time.monotonic() - start
    record['connected'] = error is None
    operation_ids = {}
    try:
        operation_ids = summary_operation_ids(run)
    except Exception:
        pass
    record['scenarios'] = [{'id': name, 'state': 'failed' if error else 'passed',
                            'operation_ids': operation_ids.get(name, []), 'seconds': elapsed,
                            'source_revision': revision, 'missing_capability': error} for name in CASES]
    descriptor = os.open(output / 'summary.pending', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(record, stream, indent=2)
    (output / 'summary.pending').replace(output / 'summary.json')
    print(json.dumps({'state': 'failed' if error else 'passed', 'missing_capability': error}))
    return 1 if error else 0


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT / 'packages' / 'runtime' / 'src'))
    raise SystemExit(main())
