"""Command and failure checks without opening a connection."""
import json
import os

import pytest

from connected import CapabilityError, database_plan, files_restore, load_inputs, main
from fixtures import DOMAINS
from restore import digest


def test_dump_command_keeps_password_out_of_arguments():
    command, env = database_plan('postgresql://test_owner:test-password@127.0.0.1:54329/test_identity',
                                 'pg_dump', '--format=custom', '--snapshot=test-snapshot')
    assert command == ['pg_dump', '--host=127.0.0.1', '--port=54329',
                       '--username=test_owner', '--dbname=test_identity',
                       '--format=custom', '--snapshot=test-snapshot']
    assert env['PGPASSWORD'] == 'test-password'
    assert 'test-password' not in ' '.join(command)
    assert set(env) <= {'PATH', 'LANG', 'PGPASSWORD'}


@pytest.mark.parametrize('url', [
    'postgresql://test_owner:test-password@localhost:54329/test_db',
    'postgresql://test_owner:test-password@127.0.0.1:5432/test_db',
    'postgresql://test_owner:test-password@192.0.2.1:54329/test_db',
    'postgresql://test_owner:test-password@127.0.0.1:54329/test_db?host=example',
    'postgresql://test_owner@127.0.0.1:54329/test_db',
])
def test_only_designated_local_source_is_allowed(url):
    with pytest.raises(CapabilityError):
        database_plan(url, 'pg_dump')


def inputs(tmp_path):
    native = {'schema_version': 1, 'services': {name: {'env': {
        'BT_MIGRATION_DATABASE_URL': f'postgresql://test_owner:test-password@127.0.0.1:54329/test_{index}'
    }} for index, name in enumerate(DOMAINS)}}
    probes = {name: {'domain': 'identity', 'operation_ids': ['test-operation'],
                     'query_id': 'test-read-v1'}
              for name in ('I07', 'O08', 'S11', 'A10')}
    for name, value in [('native-v1.json', native), ('e04-inputs.json', {
        'schema_version': 1, 'origin': 'connected', 'probes': probes,
        'file_store': {'domain': 'identity', 'query_id': 'test-read-v1',
                       'operation_ids': ['test-operation']}})]:
        path = tmp_path / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    return native


def test_input_contract_and_private_permissions(tmp_path, monkeypatch):
    register_test_reads(monkeypatch)
    inputs(tmp_path)
    urls, _ = load_inputs(tmp_path)
    assert set(urls) == set(DOMAINS)
    (tmp_path / 'native-v1.json').chmod(0o644)
    with pytest.raises(CapabilityError, match='0600'):
        load_inputs(tmp_path)


def test_runtime_credentials_are_not_owner_fallback(tmp_path):
    native = inputs(tmp_path)
    native['services']['identity']['env'] = {'BT_DATABASE_URL': 'test-runtime-url'}
    (tmp_path / 'native-v1.json').write_text(json.dumps(native))
    with pytest.raises(CapabilityError, match='owner_credentials:identity'):
        load_inputs(tmp_path)


def test_missing_capability_writes_failed_cases(tmp_path, capsys):
    assert main(['--run-dir', str(tmp_path)]) == 1
    summary = json.loads((tmp_path / 'scenarios/e04/summary.json').read_text())
    assert not summary['connected']
    assert len(summary['scenarios']) == 7
    assert all(row['state'] == 'failed' and row['seconds'] >= 0 and row['source_revision']
               for row in summary['scenarios'])
    assert 'password' not in capsys.readouterr().out
    assert os.stat(tmp_path / 'scenarios/e04/summary.json').st_mode & 0o777 == 0o600


def test_actual_files_integrity_and_tombstones(tmp_path):
    source = tmp_path / 'files'
    source.mkdir()
    (source / 'test-kept').write_bytes(b'test-file')
    rows = [{'file_id': name, 'tombstoned': deleted, 'checksum': digest(b'test-file'), 'size': 9}
            for name, deleted in [('test-kept', False), ('test-deleted', True)]]
    files_restore({'root': str(source), 'files': rows}, tmp_path / 'restored')
    assert [p.name for p in (tmp_path / 'restored').iterdir()] == ['test-kept']
    rows[0]['checksum'] = digest(b'changed')
    with pytest.raises(CapabilityError, match='integrity'):
        files_restore({'root': str(source), 'files': rows}, tmp_path / 'damaged')


def test_reserved_port_rejected_before_execution(tmp_path):
    with pytest.raises(SystemExit):
        main(['--run-dir', str(tmp_path), '--restore-port', '54329'])


@pytest.mark.asyncio
async def test_producer_invariant_cannot_be_missing_or_false(monkeypatch):
    register_test_reads(monkeypatch)
    from connected import INVARIANTS, probe
    from contextlib import asynccontextmanager

    class Connection:
        @asynccontextmanager
        async def transaction(self, **options):
            assert options == {'readonly': True}
            yield

        async def fetch(self, sql, operations):
            assert operations == ['test-operation']
            return [self.row]

    connection = Connection()
    connection.row = {'operation_id': 'test-operation', 'passed': True,
                      'producer': 'O08', 'source_revision': 1, 'authority_revision': 1,
                      'durable': True, 'seeded': False, 'synthetic': False, 'authorized': True,
                      **{field: True for field in INVARIANTS['O08']}}
    specification = {'query_id': 'test-read-v1', 'domain': 'identity',
                     'operation_ids': ['test-operation']}
    assert await probe(connection, specification, 'O08') == [connection.row]
    connection.row['journal_balanced'] = False
    with pytest.raises(CapabilityError):
        await probe(connection, specification, 'O08')


def register_test_reads(monkeypatch):
    import connected
    monkeypatch.setattr(connected, 'PRODUCER_READS', {
        name: {'query_id': 'test-read-v1', 'domain': 'identity', 'sql': 'test-query'}
        for name in (*connected.INVARIANTS, 'file_store')})


def test_unavailable_verified_reads_fail_closed(tmp_path):
    inputs(tmp_path)
    with pytest.raises(CapabilityError, match='unverified_producer_read:I07'):
        load_inputs(tmp_path)


def test_caller_cannot_supply_constant_proof(monkeypatch):
    from connected import producer_read
    register_test_reads(monkeypatch)
    specification = {'domain': 'identity', 'query_id': 'test-read-v1',
                     'operation_ids': ['test-operation'],
                     'sql': 'SELECT $1, true AS passed'}
    with pytest.raises(CapabilityError, match='unverified_producer_read:I07'):
        producer_read(specification, 'I07')
    del specification['sql']
    specification['query_id'] = 'test-unreviewed'
    with pytest.raises(CapabilityError, match='unverified_producer_read:I07'):
        producer_read(specification, 'I07')


@pytest.mark.asyncio
async def test_private_runtime_role_precedes_migration():
    from connected import prepare_private_roles

    class Connection:
        async def execute(self, sql):
            assert sql == 'CREATE ROLE e04 NOLOGIN'

    await prepare_private_roles(Connection())


def test_failed_read_keeps_each_scenarios_operation_ids(tmp_path, monkeypatch):
    import connected

    inputs(tmp_path)
    path = tmp_path / 'e04-inputs.json'
    supplied = json.loads(path.read_text())
    expected = {}
    for name, spec in [*supplied['probes'].items(), ('file_store', supplied['file_store'])]:
        spec['operation_ids'] = ['test-operation-' + name]
        expected[name] = spec['operation_ids']
    path.write_text(json.dumps(supplied))

    async def unavailable(*arguments):
        load_inputs(tmp_path)

    monkeypatch.setattr(connected, 'connected', unavailable)
    assert main(['--run-dir', str(tmp_path)]) == 1
    summary = json.loads((tmp_path / 'scenarios/e04/summary.json').read_text())
    combined = [value for values in expected.values() for value in values]
    expected.update(nine_database_restore=combined, migration=combined)
    assert {row['id']: row['operation_ids'] for row in summary['scenarios']} == expected
    assert all(row['state'] == 'failed' and
               row['missing_capability'] == 'unverified_producer_read:I07'
               for row in summary['scenarios'])
    assert summary['connected'] is False


@pytest.mark.parametrize('invalid', [[], [''], ['test-id', 'test-id'], [1], 'test-id'])
def test_summary_excludes_invalid_ids_without_discarding_other_inputs(tmp_path, invalid):
    from connected import summary_operation_ids

    inputs(tmp_path)
    path = tmp_path / 'e04-inputs.json'
    supplied = json.loads(path.read_text())
    supplied['probes']['I07']['operation_ids'] = invalid
    supplied['file_store']['operation_ids'] = ['test-file-operation']
    path.write_text(json.dumps(supplied))
    result = summary_operation_ids(tmp_path)
    assert 'I07' not in result
    assert result['O08'] == ['test-operation']
    assert result['file_store'] == ['test-file-operation']
    assert result['migration'] == ['test-operation', 'test-file-operation']


@pytest.mark.parametrize('damage', ['missing_row', 'checksum', 'missing_table'])
def test_identity_backup_integrity_precedes_authority_repair(damage):
    from connected import verify_saved_inventory

    table = '"public"."identity_private_evidence"'
    before = {table: {'rows': 1, 'sha256': 'test-original'}}
    restored = {table: dict(before[table])}
    verify_saved_inventory(before, restored, 'identity')
    if damage == 'missing_row':
        restored[table]['rows'] = 0
    elif damage == 'checksum':
        restored[table]['sha256'] = 'test-corruption'
    else:
        restored.clear()
    with pytest.raises(CapabilityError, match='restored_rows_mismatch:identity'):
        verify_saved_inventory(before, restored, 'identity')
