from http.client import BadStatusLine
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import pytest

import driver
from launcher import WholeStack
from native import Unavailable


class LauncherTests(unittest.TestCase):
    def execution(self, root, database=None):
        settings = root / 'native-v1.json'
        settings.write_text(json.dumps({'schema_version': 1, 'services': {},
                                       'e09_database': database or {}}))
        return WholeStack(root, settings)

    def test_payment_admission_failure_preserves_build_and_replacement_results(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            artifacts = {name: 'test-candidate:' + name for name in driver.SERVICES}

            def replace(name, root, artifact, **kwargs):
                return dict(service=name, before_pid=123, after_pid=124,
                            before_start='test-old', after_start='test-new',
                            artifact=artifact, ready=True)

            with patch.object(execution, 'prepare_products', side_effect=Unavailable(
                    'orders-payment-recovery-assignment-command')) as prepare, \
                    patch.object(execution, 'build', return_value={
                        'candidate': 'test-candidate', 'artifacts': artifacts}), \
                    patch.dict(execution.releases, {'test-candidate': Path(folder)}), \
                    patch.object(execution, 'replace', side_effect=replace):
                result = driver.execute(execution, 'test-revision')

            prepare.assert_called_once_with()
            rows = {row['scenario_id']: row for row in result['results']}
            self.assertEqual(rows['baseline']['missing_capability'],
                             'orders-payment-recovery-assignment-command')
            self.assertEqual(rows['release-build']['state'], 'passed')
            for name in driver.SERVICES:
                self.assertEqual(rows['restart/' + name]['state'], 'passed')
            self.assertEqual(result['state'], 'failed')
            self.assertNotIn('release/receipt-reconciliation', result['provider_evidence'])
            self.assertFalse(result['certification_accepted'])

    def test_isolation_precedes_database_access(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            with patch.object(execution, 'isolated', side_effect=Unavailable('test-isolation')), \
                    patch('launcher.subprocess.Popen') as launch:
                with self.assertRaisesRegex(Unavailable, 'test-isolation'):
                    execution.start()
                launch.assert_not_called()

    def test_existing_cluster_is_never_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cluster = root / 'e09-database'
            cluster.mkdir()
            marker = cluster / 'test-marker'
            marker.write_text('test-existing')
            execution = self.execution(root, {'schema_version': 1})
            with patch.object(execution, 'isolated'):
                with self.assertRaisesRegex(Unavailable, 'fresh-private-database'):
                    execution.start()
            execution.close()
            self.assertTrue(marker.exists())

    def test_cleanup_continues_after_one_stop_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            execution.children = dict(database={}, orders={}, web={})
            with patch.object(execution, 'stop', side_effect=[ValueError('test-stop'), None, None]) as stop:
                with self.assertRaisesRegex(ValueError, 'test-stop'):
                    execution.close()
            self.assertEqual([call.args[0] for call in stop.call_args_list],
                             ['web', 'orders', 'database'])

    def test_database_contract_missing_is_named(self):
        with tempfile.TemporaryDirectory() as folder:
            execution = self.execution(Path(folder))
            with patch.object(execution, 'isolated'), patch('launcher.subprocess.Popen') as launch:
                with self.assertRaisesRegex(Unavailable, 'private-database-input'):
                    execution.start()
                launch.assert_not_called()

    def test_owned_cluster_reclaimed_after_children_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'e09-database').mkdir()
            execution = self.execution(root)
            execution.database_owned = True
            execution.close()
            self.assertFalse((root / 'e09-database').exists())

    def test_restore_scratch_is_reclaimed_only_after_owned_group_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scratch = root / 'test-restore-scratch'
            scratch.mkdir()
            execution = self.execution(root)
            execution.restore_scratch = scratch
            execution.children['restore-database'] = {}
            with patch.object(execution, 'stop', side_effect=Unavailable('test-stop-timeout')):
                with self.assertRaisesRegex(Unavailable, 'test-stop-timeout'):
                    execution.close()
            self.assertTrue(scratch.is_dir())
            with patch.object(execution, 'stop', side_effect=execution.children.pop):
                execution.close()
            self.assertFalse(scratch.exists())

    def test_provisioning_access_rejected_before_starting_children(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cluster = root / 'cluster'
            cluster.mkdir()
            execution = self.execution(root)
            rules = ['host all all 127.0.0.1/32 scram-sha-256']
            execution.database_socket = root
            probes = [Mock(returncode=0, stdout=b't\n'),
                      Mock(returncode=0, stderr=b''), Mock(returncode=2,
                      stderr=b'pg_hba.conf rejects connection for host "[local]"')]
            with patch('launcher.subprocess.run', side_effect=probes) as probe:
                execution.seal_database(cluster, root, {}, rules)
            text = (cluster / 'pg_hba.conf').read_text()
            self.assertTrue(text.startswith('local all all reject\n'))
            self.assertLess(text.index('host all e09_owner 127.0.0.1/32 reject'),
                            text.index(rules[0]))
            self.assertNotIn('trust', text)
            self.assertEqual(probe.call_count, 3)
            self.assertEqual(probe.call_args_list[0].args[0][-1], 'SELECT pg_reload_conf()')

    def test_failed_authentication_cutover_aborts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            execution = self.execution(root)
            execution.database_socket = root
            with patch('launcher.subprocess.run', side_effect=[
                    Mock(returncode=0, stdout=b't\n'),
                    Mock(returncode=2, stderr=b'test-unrelated-error')]), \
                    patch('launcher.time.monotonic', side_effect=[0, 11]):
                with self.assertRaisesRegex(Unavailable, 'provisioning-access-revoked'):
                    execution.seal_database(root, root, {}, [])


@pytest.mark.parametrize('outcome', [
    'success', 'interrupted', 'missing-reference', 'existing', 'changed-dump', 'unchanged-watermark', 'omitted-domain',
])
def test_backup_captures_dumps_before_live_watermark_commands(tmp_path, outcome):
    from launcher import contract_digest, file_digest
    from recovery import DOMAINS

    execution = LauncherTests().execution(tmp_path)
    execution.settings['postgres_bin'] = '/tmp/test-bin'
    execution.children['database'] = {'child': Mock()}
    producer = tmp_path / 'retained.py'
    producer.touch()
    root = tmp_path / 'e04-backup'
    if outcome == 'existing':
        root.mkdir()
    references = ['test-baseline', 'test-recovered']
    required = {domain: references if domain == 'orders' else ['test-' + domain]
                for domain in DOMAINS}
    captured = {domain: [{'operation_id': ref} for ref in ids] for domain, ids in required.items()}
    request = dict(source_revision='test-current', acknowledged_product_ids=references)
    backup = {domain: dict(deletions='test-old', revocations='test-old') for domain in DOMAINS}
    current = {domain: dict(deletions='test-new', revocations='test-new') for domain in DOMAINS}
    phases = []
    capture = {}

    def spawn(name, argv, cwd, env, stdin):
        assert name == 'backup-producer'
        assert argv[1:] == [str(producer), '--run-dir', str(tmp_path), '--output-dir', str(root)]
        assert cwd == tmp_path
        payload = json.load(stdin)
        phase = payload.pop('phase')
        point = payload.pop('backup_watermarks' if phase == 'capture' else 'current_watermarks')
        assert point == (backup if phase == 'capture' else current)
        phases.append(phase)
        value = dict(schema_version=1, root=str(root), source_revision='test-current')
        if phase == 'capture':
            value['domains'] = {}
            for domain in DOMAINS:
                path = root / (domain + '.dump')
                path.write_bytes(b'test-dump')
                value['domains'][domain] = dict(
                    dump=path.name, dump_sha256=file_digest(path), schema_revision='test-schema',
                    operation_ids=(references[:1] if outcome == 'missing-reference' and domain == 'orders'
                                   else ['test-other'] if outcome == 'omitted-domain' and domain == 'catalog'
                                   else required[domain]),
                )
            value['backup_watermarks'] = point
            capture.update(value)
            descriptor = root / 'capture.json'
        else:
            assert phases == ['capture', 'product-commands', 'finalize']
            assert payload.pop('capture_reference') == contract_digest(capture)
            value.update(domains=capture['domains'], capture_reference=contract_digest(capture),
                         watermark_points={'backup': backup, 'current': current})
            if outcome == 'changed-dump':
                (root / 'orders.dump').write_bytes(b'test-replaced')
            descriptor = root / 'handoff.json'
        assert payload == {'schema_version': 1, 'source_revision': 'test-current',
                           'required_operation_ids': required}
        descriptor.write_text(json.dumps(value))
        descriptor.chmod(0o600)
        if outcome == 'interrupted':
            raise driver.Interrupted('test-interrupted')
        return {'child': Mock(returncode=0)}

    def journey(name):
        assert name == 'e09_watermark_journey'
        phases.append('product-commands')

    measured = [backup, backup, backup if outcome == 'unchanged-watermark' else current]
    with patch('launcher.BACKUP_PRODUCER', producer), patch.object(execution, 'isolated'), \
            patch('launcher.running', side_effect=[True, False, False]), \
            patch('launcher.live_acknowledged', return_value=captured), \
            patch('launcher.live_watermarks', side_effect=measured), \
            patch.object(execution, 'prepare_products', side_effect=journey), \
            patch.object(execution, 'spawn', side_effect=spawn) as launch, \
            patch.object(execution, 'stop'), patch('launcher.consume') as consume:
        if outcome == 'success':
            assert execution.restore(request) is consume.return_value
            assert consume.call_args.args[2] == captured
            assert consume.call_args.args[1]['watermark_points'] == {'backup': backup, 'current': current}
        elif outcome == 'interrupted':
            with pytest.raises(driver.Interrupted):
                execution.restore(request)
        else:
            reason = {
                'existing': 'fresh-private-backup',
                'omitted-domain': 'backup-acknowledged-references',
                'missing-reference': 'backup-acknowledged-references',
                'changed-dump': 'backup-file-hash',
                'unchanged-watermark': 'product-watermark-transition-deletions',
            }[outcome]
            with pytest.raises(Unavailable, match=reason):
                execution.restore(request)
        if outcome != 'success':
            consume.assert_not_called()
        if outcome == 'existing':
            launch.assert_not_called()
        if outcome == 'unchanged-watermark':
            assert phases == ['capture', 'product-commands']
    assert root.exists() == (outcome == 'existing')


@pytest.mark.parametrize('service', ['database', 'restore-database'])
def test_postgres_initializes_only_after_namespace_ownership(tmp_path, service):
    execution = LauncherTests().execution(tmp_path)
    entry = {'child': Mock(pid=123), 'session': 123}
    scratch = tmp_path / 'scratch' if service == 'restore-database' else None
    cluster = (scratch or tmp_path) / 'test-cluster'
    cluster.mkdir(parents=True)

    def spawn(name, argv, cwd, env, *, stdin, pass_fds):
        assert name == service
        assert '--unshare-pid' in argv and '--die-with-parent' in argv
        memory_mount = argv.index('/dev/shm')
        assert argv[memory_mount - 1:memory_mount + 1] == ['--tmpfs', '/dev/shm']
        assert argv.index('--dev') < memory_mount < argv.index('--')
        mount = str(scratch or cluster)
        assert argv[argv.index('--bind') + 1:argv.index('--bind') + 3] == [mount, mount]
        assert argv[argv.index('-h') + 1] == ('' if scratch else '127.0.0.1')
        assert argv[argv.index('-p') + 1] == ('55439' if scratch else '54329')
        script, _, bin_dir, data_dir, owner = argv[argv.index('-c') + 1:argv.index('-h')]
        assert (bin_dir, data_dir) == (str(tmp_path), str(cluster))
        assert owner == ('e09_restore' if scratch else 'e09_owner')
        assert script.index('read -r start') < script.index('"$bin/initdb"') < script.index('exec "$bin/postgres"')
        assert '--encoding=UTF8' in script
        assert script.startswith('set -eu\n')
        assert argv[argv.index('--info-fd') + 1] == str(pass_fds[0])
        os.write(pass_fds[0], b'{"child-pid":124}\n')
        return entry

    child_gate = None
    def retain_gate(*args, **kwargs):
        nonlocal child_gate
        child_gate = os.dup(kwargs['stdin'].fileno())
        os.set_blocking(child_gate, False)
        return spawn(*args, **kwargs)

    def claim(pid):
        assert pid == 124
        with pytest.raises(BlockingIOError):
            os.read(child_gate, 1)
        return 200

    try:
        with patch.object(execution, 'spawn', side_effect=retain_gate), \
                patch('launcher.os.getsid', return_value=123), \
                patch('launcher.os.pidfd_open', side_effect=claim):
            assert execution.start_database(cluster, tmp_path, {}, service=service, scratch=scratch) is entry
        assert entry['namespace_fd'] == 200
        assert os.read(child_gate, 16) == b'start\n'
    finally:
        if child_gate is not None:
            os.close(child_gate)


@pytest.mark.parametrize('exited', [True, False])
@pytest.mark.parametrize('service', ['database', 'restore-database'])
def test_cluster_cleanup_waits_for_namespace_exit(tmp_path, exited, service):
    execution = LauncherTests().execution(tmp_path)
    if service == 'database':
        execution.database_owned = True
        cluster = tmp_path / 'e09-database'
    else:
        cluster = tmp_path / 'test-restore-scratch'
        execution.restore_scratch = cluster
    cluster.mkdir()
    execution.children[service] = {'namespace_fd': 200}
    poll = Mock()
    poll.poll.return_value = [(200, 1)] if exited else []

    real_close = os.close
    def close_namespace(fd):
        if fd != 200:
            real_close(fd)

    with patch('launcher.signal.pidfd_send_signal') as kill, \
            patch('launcher.select.poll', return_value=poll), \
            patch('launcher.os.close', side_effect=close_namespace) as close, \
            patch('native.Execution.stop', side_effect=execution.children.pop) as stop:
        if exited:
            execution.close()
            stop.assert_called_once_with(service)
            close.assert_any_call(200)
        else:
            with pytest.raises(Unavailable, match='owned-database-namespace-stop'):
                execution.close()
            stop.assert_not_called()
            assert not any(call.args == (200,) for call in close.call_args_list)
        kill.assert_called_once_with(200, __import__('signal').SIGKILL)
    assert cluster.exists() is not exited


def test_live_database_start_failure_reclaims_owned_cluster(tmp_path):
    bootstrap = tmp_path / 'bootstrap.sql'
    authentication = tmp_path / 'pg_hba.conf'
    for path in (bootstrap, authentication):
        path.touch(mode=0o600)
    authentication.write_text('host all all 127.0.0.1/32 scram-sha-256\n')
    execution = LauncherTests().execution(tmp_path, {
        'schema_version': 1, 'bootstrap_sql': str(bootstrap),
        'authentication_file': str(authentication),
    })
    execution.settings['postgres_bin'] = str(tmp_path)
    with patch.object(execution, 'isolated'), \
            patch('launcher.subprocess.run', return_value=Mock(stdout=b'postgres 17.1')), \
            patch.object(execution, 'command') as command, \
            patch.object(execution, 'start_database', side_effect=Unavailable('test-stop')) as start:
        with pytest.raises(Unavailable, match='test-stop'):
            execution.start()
    command.assert_not_called()
    start.assert_called_once()
    assert not (tmp_path / 'e09-database').exists()


def test_losing_cluster_claim_preserves_winning_cluster(tmp_path):
    bootstrap = tmp_path / 'bootstrap.sql'
    authentication = tmp_path / 'pg_hba.conf'
    bootstrap.touch(mode=0o600)
    authentication.touch(mode=0o600)
    authentication.write_text('host all all 127.0.0.1/32 scram-sha-256\n')
    execution = LauncherTests().execution(tmp_path, {
        'schema_version': 1, 'bootstrap_sql': str(bootstrap),
        'authentication_file': str(authentication),
    })
    execution.settings['postgres_bin'] = str(tmp_path)
    cluster = tmp_path / 'e09-database'
    marker = cluster / 'test-cluster-marker'

    def competing_claim(*args, **kwargs):
        cluster.mkdir(mode=0o700)
        marker.write_text('test-winning-cluster')
        return Mock(stdout=b'postgres 17.1')

    with patch.object(execution, 'isolated'), \
            patch('launcher.subprocess.run', side_effect=competing_claim), \
            patch.object(execution, 'command') as initdb:
        with pytest.raises(Unavailable, match='fresh-private-database'):
            execution.start()
    initdb.assert_not_called()
    execution.close()
    assert marker.read_text() == 'test-winning-cluster'


def test_restored_orders_must_contain_the_live_product_records(tmp_path):
    execution = LauncherTests().execution(tmp_path)
    with patch.object(execution, 'reads', return_value={'receipts': ['test-live']}), \
            patch('observations.read_orders', return_value={'receipts': []}):
        with pytest.raises(Unavailable, match='restored-orders-product-records'):
            execution.verify_restored_orders(['-d', 'test-restored'], ['-d', 'test-restored-communications'])


@pytest.mark.parametrize('failure', [None, 'rows', 'query', 'role', 'role-query', 'timeout'])
def test_provisioned_databases_require_restricted_roles_and_no_business_rows(tmp_path, failure):
    from recovery import DOMAINS

    execution = LauncherTests().execution(tmp_path)
    execution.database_socket = tmp_path / 'socket'

    def environment(domain, root):
        return {'BT_DATABASE_URL': f'postgresql://test_{domain}:test-runtime@127.0.0.1:54329/test_{domain}'}

    def probe(argv, **kwargs):
        database = argv[argv.index('-d') + 1]
        role = next((value for value in argv if value.startswith('runtime_role=')), None)
        if role:
            assert role == 'runtime_role=' + database
            assert b"runtime.rolname = :'runtime_role'" in kwargs['input']
            if database == 'test_orders':
                if failure == 'timeout':
                    from subprocess import TimeoutExpired
                    raise TimeoutExpired(argv, 30)
                if failure == 'role-query':
                    return Mock(returncode=1, stdout=b'')
                if failure == 'role':
                    return Mock(returncode=0, stdout=b'')
            return Mock(returncode=0, stdout=b'1\n')
        assert kwargs['input'].startswith(b'\nBEGIN READ ONLY;')
        assert argv[argv.index('-U') + 1] == 'e09_owner'
        dictionary = next(value for value in argv if value.startswith('dictionary='))
        assert dictionary == ('dictionary=catalog_discovery_aliases_v1'
                              if database == 'test_catalog' else 'dictionary=')
        if database == 'test_orders':
            return Mock(returncode=int(failure == 'query'), stdout=b'1\n' if failure == 'rows' else b'')
        return Mock(returncode=0, stdout=b'')

    with patch.object(execution, 'environment', side_effect=environment), \
            patch('launcher.subprocess.run', side_effect=probe) as run:
        if failure:
            reason = {
                'rows': 'orders-provisioned-business-records',
                'query': 'orders-provisioned-database-check',
                'role': 'orders-restricted-runtime-role',
                'role-query': 'orders-restricted-runtime-role',
                'timeout': 'orders-provisioned-database-timeout',
            }[failure]
            with pytest.raises(Unavailable, match=reason):
                execution.verify_runtime_databases(tmp_path, {})
        else:
            execution.verify_runtime_databases(tmp_path, {})
            assert run.call_count == 2 * len(DOMAINS)


def test_interruption_after_reaping_allows_cluster_reclamation(tmp_path):
    execution = LauncherTests().execution(tmp_path)
    cluster = tmp_path / 'e09-database'
    cluster.mkdir()
    execution.database_owned = True
    child = Mock(pid=123)
    reader = Mock()
    reader.join.side_effect = driver.Interrupted('test-termination')
    execution.children['orders'] = dict(child=child, start='test-start', session=123, reader=reader)
    with patch('native.ticks', return_value='test-start'), \
            patch('native.os.getsid', return_value=123), patch('native.Path.glob', return_value=[]):
        with pytest.raises(driver.Interrupted, match='test-termination'):
            execution.stop('orders')
    child.wait.assert_called_once_with(timeout=5)
    assert 'orders' not in execution.children
    execution.close()
    assert not cluster.exists()


@pytest.mark.parametrize('directory', ['e09-database', 'e09-database-socket'])
def test_database_reclamation_failure_preserves_ownership_for_retry(tmp_path, directory):
    import shutil

    execution = LauncherTests().execution(tmp_path)
    cluster = tmp_path / 'e09-database'
    socket = execution.database_socket = tmp_path / 'e09-database-socket'
    cluster.mkdir()
    socket.mkdir()
    execution.database_owned = True
    remove = shutil.rmtree

    def reclaim(path):
        if path.name == directory:
            raise PermissionError('test-reclamation-denied')
        remove(path)

    with patch('launcher.shutil.rmtree', side_effect=reclaim):
        with pytest.raises(PermissionError, match='test-reclamation-denied'):
            execution.close()
    assert execution.database_owned
    assert (tmp_path / directory).is_dir()

    execution.close()
    assert not execution.database_owned
    assert not cluster.exists() and not socket.exists()


@pytest.mark.parametrize(('journey_error', 'error_type', 'reason'), [
    (None, Unavailable, 'communications-payment-confirmed-delivery'),
    (Unavailable('product-preparation-outcome'), Unavailable, 'product-preparation-outcome'),
    (BadStatusLine('test-malformed-status'), BadStatusLine, 'test-malformed-status'),
    (driver.Interrupted('rehearsal-interrupted'), driver.Interrupted, 'rehearsal-interrupted'),
])
def test_baseline_acknowledgements_survive_journey_or_inbox_failure(
        tmp_path, journey_error, error_type, reason):
    execution = LauncherTests().execution(tmp_path)
    with patch.object(execution, 'prepare_products', side_effect=journey_error), \
            patch.object(execution, 'owned_database', return_value=['-d', 'test-orders']), \
            patch('observations.acknowledged_payments', return_value={'test-baseline'}) as acknowledged, \
            patch.object(execution, 'reads', return_value={
                'receipts': [{'operation_id': 'test-baseline'}], 'inbox': []}), \
            patch.object(execution, 'await_payment_inbox', side_effect=Unavailable(
                'communications-payment-confirmed-delivery')):
        with pytest.raises(error_type, match=reason):
            execution.call('authoritative-reads', {})
    acknowledged.assert_called_once_with(['-d', 'test-orders'])
    assert execution.acknowledged_baseline_ids == {'test-baseline'}


def test_interrupted_baseline_records_durable_reference_before_cleanup(tmp_path):
    execution = LauncherTests().execution(tmp_path)
    summary = driver.new_summary('test-revision')
    with patch.object(execution, 'prepare_products', side_effect=driver.Interrupted(
            'rehearsal-interrupted')), patch.object(execution, 'owned_database',
            return_value=['-d', 'test-orders']), patch('observations.acknowledged_payments',
            return_value={'test-committed-payment'}):
        with pytest.raises(driver.Interrupted, match='rehearsal-interrupted'):
            driver.execute(execution, 'test-revision', summary=summary)
    baseline, = summary['results']
    assert baseline['state'] == 'failed'
    assert baseline['missing_capability'] == 'scenario-interrupted'
    assert baseline['acknowledged_baseline_ids'] == ['test-committed-payment']
    assert baseline['product_operation_ids'] == ['test-committed-payment']
