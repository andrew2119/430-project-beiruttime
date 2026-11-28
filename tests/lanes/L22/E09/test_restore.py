import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from driver import Interrupted
from native import Unavailable
from recovery import DOMAINS
from restore import LostAcknowledgedOperations, consume, contract_digest, watermark_digest


@pytest.mark.parametrize('mismatch', [None, 'missing-from-dump', 'omitted-domain-reference', 'changed-before-replay', 'extra-before-replay', 'replay-changed-payment', 'operations', 'deletions', 'revocations', 'queries', 'empty-deletions', 'empty-revocations', 'unchanged-deletions', 'unchanged-revocations', 'one-domain-watermarks', 'schema-revision', 'wrong-dump-schema', 'wrong-live-schema', 'changed-replay-schema', 'wrong-backup-point', 'wrong-current-point'])
@pytest.mark.parametrize('startup', [None, 'timeout', 'readiness', 'interrupted'])
def test_restore_measures_all_domains_and_reclaims(tmp_path, mismatch, startup):
    root = tmp_path / 'e04-backup'
    root.mkdir(mode=0o700)
    domains = {}
    for domain in DOMAINS:
        item = dict(operation_ids=['test-operation'], schema_revision='test-schema',
                    queries={name: 'SELECT ' + name for name in
                             ('operations', 'deletions', 'revocations', 'schema')})
        for field in ('dump', 'watermarks'):
            name = domain + '.' + field
            (root / name).write_bytes(b'test-private-backup')
            item[field] = name
            item[field + '_sha256'] = hashlib.sha256(b'test-private-backup').hexdigest()
        domains[domain] = item
    captured = {domain: [{'operation_id': 'test-operation'}] for domain in DOMAINS}
    if mismatch == 'omitted-domain-reference':
        captured[DOMAINS[0]].append({'operation_id': 'test-omitted'})
    if mismatch == 'changed-before-replay':
        captured[DOMAINS[0]][0]['revision'] = 2
    import json
    relative = 'recovery/domain-reads-v1.json'
    reviewed = tmp_path / 'reviewed'
    (reviewed / 'recovery').mkdir(parents=True)
    raw = json.dumps({domain: item.pop('queries') for domain, item in domains.items()}).encode()
    (reviewed / relative).write_bytes(raw)
    schema = contract_digest({name: item['schema_revision'] for name, item in domains.items()})
    empty = watermark_digest([])
    populated = watermark_digest([{'operation_id': 'test-operation'}])
    points = {
        'backup': {domain: {name: populated if mismatch == 'unchanged-' + name else empty
                            for name in ('deletions', 'revocations')} for domain in DOMAINS},
        'current': {domain: {
            name: empty if (mismatch == 'empty-' + name or
                            (mismatch == 'one-domain-watermarks' and domain != DOMAINS[0]))
            else populated for name in ('deletions', 'revocations')} for domain in DOMAINS},
    }
    execution = SimpleNamespace(reviewed_prior=(reviewed, {relative: hashlib.sha256(raw).hexdigest()}), run=tmp_path, settings=dict(postgres_bin='/tmp/test-bin',
        e04_backup=dict(schema_version=1, root=str(root), source_revision='test-source',
                        schema_revision=schema, domains=domains, capture_reference='test-capture',
                        watermark_points=points)),
        partial_measurements={},
        children={d: {'root': tmp_path} for d in DOMAINS},
        owned_database=lambda *args: ['-d', 'test-runtime-url'])
    if mismatch in ('wrong-backup-point', 'wrong-current-point'):
        point = 'backup' if mismatch == 'wrong-backup-point' else 'current'
        points[point][DOMAINS[0]]['deletions'] = 'test-wrong-point'
    child = Mock()
    execution.verify_restored_orders = Mock(side_effect=[
        {'receipts': ['test-before']} if mismatch == 'replay-changed-payment' else
        {'receipts': ['test-restored']}, {'receipts': ['test-restored']},
    ])
    execution.start_database = Mock(return_value={'child': child})
    execution.stop = Mock(side_effect=lambda _: assert_scratch_exists(execution))
    if mismatch == 'schema-revision':
        execution.settings['e04_backup']['schema_revision'] = 'test-conflicting-schema'
        with pytest.raises(Unavailable, match='backup-schema-revision'):
            consume(execution, execution.settings['e04_backup'], captured)
        execution.start_database.assert_not_called()
        assert not root.exists()
        return
    if mismatch in ('queries', 'omitted-domain-reference'):
        if mismatch == 'queries':
            domains[DOMAINS[0]]['queries'] = {'operations': 'SELECT 1'}
        reason = ('restore-measurement-queries' if mismatch == 'queries'
                  else 'backup-acknowledged-references')
        with pytest.raises(Unavailable, match=reason), \
                patch('restore.subprocess.run', return_value=Mock(returncode=0, stdout=b' 17.1')):
            consume(execution, execution.settings['e04_backup'], captured)
        execution.start_database.assert_not_called()
        assert not root.exists()
        return
    def run(argv, **kwargs):
        output = b''
        if 'pg_isready' in argv[0] and startup:
            if startup == 'timeout':
                import subprocess
                raise subprocess.TimeoutExpired(argv, 2)
            if startup == 'interrupted':
                raise Interrupted('test-interrupted')
            raise Unavailable('test-readiness')
        if '--version' in argv:
            output = b'PostgreSQL 17.1'
        elif '-qAt' in argv:
            # Query order follows the versioned measurement map.
            number = run.count // 2 % 4
            output = (b'[{"revision":"test-schema"}]' if number == 3 else
                      b'[{"operation_id":"test-operation"}]')
            names = ('operations', 'deletions', 'revocations', 'schema')
            if mismatch == 'changed-replay-schema' and number == 3:
                output = b'[{"revision":"test-wrong"}]'
            if mismatch == 'empty-' + names[number]:
                output = b'[]'
            if mismatch == 'one-domain-watermarks' and run.count >= 8 and number in (1, 2):
                output = b'[]'
            if mismatch == names[number] and run.count == 2 * number:
                output = b'[]'
            run.count += 1
        return Mock(returncode=0, stdout=output)
    run.count = 0
    def measured(connection, query):
        import json
        if apply.call_count == 0:
            before_queries.append(query)
            if query == 'SELECT schema':
                wrong_connection = ('test-runtime-url' if mismatch == 'wrong-live-schema'
                                    else 'restore_0' if mismatch == 'wrong-dump-schema' else None)
                return [{'revision': 'test-wrong' if connection[-1] == wrong_connection else 'test-schema'}]
            if query == 'SELECT operations':
                if mismatch == 'extra-before-replay' and connection[-1] == 'restore_0':
                    return [{'operation_id': 'test-operation'}, {'operation_id': 'test-extra'}]
                return [] if mismatch == 'missing-from-dump' else [{'operation_id': 'test-operation'}]
            if mismatch == 'unchanged-' + query.removeprefix('SELECT '):
                return [{'operation_id': 'test-operation'}]
            return []
        return json.loads(run(['-qAt', query]).stdout)
    before_queries = []
    with patch('restore.subprocess.run', side_effect=run) as invoked, \
            patch('restore.measure', side_effect=measured), \
            patch('restore.apply_watermarks') as apply, \
            patch('restore.running', return_value=True):
        if startup:
            import subprocess
            with pytest.raises((Unavailable, subprocess.TimeoutExpired, Interrupted)):
                consume(execution, execution.settings['e04_backup'], captured)
            execution.stop.assert_called_once_with('restore-database')
            child.poll.assert_not_called()
            assert not root.exists()
            assert not list(tmp_path.glob('e09-restore-*'))
            return
        if mismatch not in (None, 'one-domain-watermarks'):
            reason = ('current-restore-' + mismatch.split('-', 1)[1]
                      if mismatch.startswith(('empty-', 'unchanged-')) else 'measured-restore-' + mismatch)
            reason = {
                'operations': 'lost-acknowledged-operations',
                'missing-from-dump': 'lost-acknowledged-operations',
                'changed-before-replay': 'restored-acknowledged-records-' + DOMAINS[0],
                'extra-before-replay': 'restored-acknowledged-records-' + DOMAINS[0],
                'replay-changed-payment': 'watermark-replay-changed-payment-records',
                'changed-replay-schema': 'restored-schema-revision',
                'wrong-dump-schema': 'restored-backup-schema-revision-' + DOMAINS[0],
                'wrong-live-schema': 'restored-backup-schema-revision-' + DOMAINS[0],
                'wrong-backup-point': 'restored-backup-watermark-deletions',
                'wrong-current-point': 'restored-current-watermark-deletions',
            }.get(mismatch, reason)
            with pytest.raises(Unavailable, match=reason) as failure:
                consume(execution, execution.settings['e04_backup'], captured)
            if mismatch in ('operations', 'missing-from-dump'):
                assert isinstance(failure.value, LostAcknowledgedOperations)
                assert failure.value.references == ['test-operation']
                assert execution.partial_measurements['lost_acknowledged_operations'] == ['test-operation']
            assert not root.exists()
            if mismatch in ('missing-from-dump', 'changed-before-replay', 'extra-before-replay',
                            'wrong-dump-schema', 'wrong-live-schema'):
                apply.assert_not_called()
                assert all('GRANT INSERT' not in call.args[0][-1]
                           for call in invoked.call_args_list)
            execution.stop.assert_called_once_with('restore-database')
            child.poll.assert_not_called()
            return
        result = consume(execution, execution.settings['e04_backup'], captured)
    execution.stop.assert_called_once_with('restore-database')
    cluster, _, _ = execution.start_database.call_args.args
    work = execution.start_database.call_args.kwargs['scratch']
    assert execution.start_database.call_args.kwargs['service'] == 'restore-database'
    assert cluster == work / 'cluster'
    assert work.parent == tmp_path and not work.exists()
    child.poll.assert_not_called()
    assert set(result['restored_domains']) == set(DOMAINS)
    assert run.count == len(DOMAINS) * 8
    assert apply.call_count == len(DOMAINS)
    assert before_queries == ['SELECT schema', 'SELECT schema', 'SELECT deletions', 'SELECT revocations', 'SELECT operations'] * len(DOMAINS)
    assert execution.verify_restored_orders.call_count == 2
    assert execution.verify_restored_orders.call_args_list[0] == execution.verify_restored_orders.call_args_list[1]
    execution.verify_restored_orders.assert_called_with(*[
        ['-h', str(work), '-p', '55439', '-U', 'e09_watermark', '-d',
         'restore_' + str(DOMAINS.index(domain))] for domain in ('orders', 'communications')
    ])
    assert all('initdb' not in call.args[0][0] or '--version' in call.args[0]
               for call in invoked.call_args_list)
    assert sum("ENCODING 'UTF8'" in call.args[0][-1]
               for call in invoked.call_args_list) == len(DOMAINS)
    assert all('-f' not in call.args[0] for call in invoked.call_args_list)
    assert result['receipts'] == ['test-restored']
    assert result['lost_acknowledged_operations'] == []
    assert result['current_deletions_applied'] is True
    assert result['current_revocations_applied'] is True
    spec = execution.settings['e04_backup']
    descriptor = {key: value for key, value in spec.items() if key != 'root'}
    assert result['backup_reference'] == contract_digest(descriptor)
    domains['orders']['dump_sha256'] = hashlib.sha256(b'test-new-dump').hexdigest()
    assert result['backup_reference'] != contract_digest(descriptor)
    assert not root.exists()
    assert any('pg_restore' in call.args[0][0] for call in invoked.call_args_list)


def assert_scratch_exists(execution):
    assert execution.restore_scratch.is_dir()


def test_missing_handoff_is_named(tmp_path):
    with pytest.raises(Unavailable, match='E04-connected-backup-output'):
        consume(SimpleNamespace(), {}, {})


def test_measurement_uses_single_statement_protocol_and_read_only_transaction():
    from restore import measure
    client = Mock()
    client.PQconnectdbParams.return_value = 1
    client.PQstatus.return_value = 0
    client.PQexecParams.return_value = 2
    client.PQresultStatus.side_effect = [1, 1, 7]
    malicious = 'SELECT 1) measured; COMMIT; DELETE FROM retained; SELECT 1'
    with patch('restore.ctypes.util.find_library', return_value='test-library'), \
            patch('restore.ctypes.CDLL', return_value=client):
        with pytest.raises(Unavailable, match='restore-measurement-statement'):
            measure(['-d', 'test-database'], malicious)
    calls = client.PQexecParams.call_args_list
    assert calls[0].args[1] == b'BEGIN READ ONLY'
    assert len(calls) == 3
    assert malicious.encode() in calls[2].args[1]
    assert all(call.args[2:] == (0, None, None, None, None, 0) for call in calls)
    assert client.PQclear.call_count == 3
    client.PQfinish.assert_called_once_with(1)

@pytest.mark.parametrize('statement', [
    'UPDATE retained SET revoked = true',
    r'\connect test-other',
    r'\! test-command',
])
def test_watermark_file_uses_only_the_disposable_sql_connection(tmp_path, statement):
    from restore import apply_watermarks

    path = tmp_path / 'watermarks.sql'
    path.write_text(statement)
    client = Mock()
    client.PQconnectdbParams.return_value = 1
    client.PQstatus.return_value = 0
    client.PQexecParams.return_value = 2
    permitted = statement.startswith('UPDATE')
    client.PQresultStatus.side_effect = [1, 1, 1, 1] if permitted else [1, 1, 7]
    with patch('restore.ctypes.util.find_library', return_value='test-library'), \
            patch('restore.ctypes.CDLL', return_value=client), \
            patch('restore.subprocess.Popen') as spawn:
        if permitted:
            apply_watermarks(tmp_path, 'restore_0', path)
        else:
            with pytest.raises(Unavailable, match='restore-measurement-statement'):
                apply_watermarks(tmp_path, 'restore_0', path)
        spawn.assert_not_called()
    keys, values, expand = client.PQconnectdbParams.call_args.args
    assert expand == 0
    assert dict(zip(keys, values)) == {
        b'host': str(tmp_path).encode(), b'port': b'55439',
        b'user': b'e09_watermark', b'dbname': b'restore_0',
        b'connect_timeout': b'10', None: None,
    }
    calls = client.PQexecParams.call_args_list
    assert calls[2].args == (1, statement.encode(), 0, None, None, None, None, 0)
    assert len(calls) == (4 if permitted else 3)
    client.PQfinish.assert_called_once_with(1)


def test_capture_reads_acknowledged_operations_from_every_live_domain():
    from restore import live_acknowledged

    queries = {domain: {'operations': 'SELECT ' + domain} for domain in DOMAINS}
    execution = SimpleNamespace(owned_database=lambda domain: ['-d', domain])
    rows = {domain: [{'operation_id': 'test-' + domain, 'revision': 2}] for domain in DOMAINS}
    with patch('restore.reviewed_queries', return_value=queries), \
            patch('restore.measure', side_effect=lambda db, query: rows[db[-1]]) as measure:
        assert live_acknowledged(execution) == rows
        assert [call.args for call in measure.call_args_list] == [
            (['-d', domain], queries[domain]['operations']) for domain in DOMAINS]
        rows['catalog'] = []
        with pytest.raises(Unavailable, match='live-acknowledged-operations-catalog'):
            live_acknowledged(execution)
