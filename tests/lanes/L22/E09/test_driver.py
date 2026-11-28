import contextlib
import io
import os
import subprocess
import unittest
from unittest.mock import patch
import pytest

import driver
from native import Unavailable


class DriverTests(unittest.TestCase):
    def check_print_mode(self, entry, whole_stack):
        output = io.StringIO()
        with patch.dict(os.environ, {'E09_MODE': 'railway'}), \
                patch('sys.argv', [entry, '--run-dir', '/tmp/test-e09-unused']), \
                patch.object(driver, 'Native', side_effect=AssertionError), \
                patch.object(driver.subprocess, 'run', side_effect=AssertionError), \
                patch.object(driver.Path, 'mkdir', side_effect=AssertionError), \
                contextlib.redirect_stdout(output):
            self.assertEqual(driver.main(whole_stack=whole_stack), 0)
        self.assertEqual(output.getvalue().splitlines(), [
            *('railway up --service ' + s + ' --detach' for s in driver.SERVICES),
            'railway rollback --service orders'])

    def test_print_mode_has_no_side_effects(self):
        for entry, whole_stack in (('driver.py', False), ('launcher.py', True)):
            with self.subTest(entry=entry):
                self.check_print_mode(entry, whole_stack)

    def test_missing_adapter_names_every_required_case(self):
        class Provider:
            def call(self, action, request):
                raise Unavailable(action + '-unavailable')
        result = driver.execute(Provider(), 'test-revision')
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(len(result['results']), 16)
        self.assertTrue(all(r['state'] == 'failed' for r in result['results']))
        self.assertEqual(result['results'][0]['missing_capability'],
                         'authoritative-reads-unavailable')

    def test_substitute_cannot_count_as_connected(self):
        class Substitute:
            def call(self, action, request):
                return {**request, 'source': 'native', 'synthetic': True,
                        'seeded': False, 'state': 'passed'}
        result = driver.execute(Substitute(), 'test-revision')
        self.assertEqual(result['state'], 'failed')
        self.assertTrue(result['results'][0]['missing_capability'].endswith('connected-source'))

    def test_reconciliation_requires_authoritative_coverage_and_one_effect(self):
        receipt = {'operation_id': 'test-operation', 'amount_minor': 100,
                   'currency': 'USD', 'custody_reference': 'test-receipt', 'revision': 1,
                   'paid': True, 'order_state': 'paid_held', 'attempt_state': 'confirmed'}
        journal = {**receipt, 'effect_count': 1}
        self.assertEqual(driver.reconcile_reads([receipt], [journal], [receipt]),
                         ['test-operation'])
        for receipts, money, custody in (([], [], []), ([receipt], [], [receipt]),
                ([receipt], [{**journal, 'effect_count': 2}], [receipt]),
                ([receipt], [journal], [{**receipt, 'revision': 2}]),
                ([{**receipt, 'paid': False}], [journal], [receipt]),
                ([{**receipt, 'order_state': 'cancelled'}], [journal], [receipt]),
                ([{**receipt, 'attempt_state': 'declined'}], [journal], [receipt]),
                ([receipt, receipt], [journal, journal], [receipt, receipt])):
            with self.assertRaises(driver.Missing):
                driver.reconcile_reads(receipts, money, custody)

    def test_final_reconciliation_retains_new_command_economics(self):
        def rows(reference):
            receipt = dict(operation_id=reference, amount_minor=100, currency='USD',
                           custody_reference='test-custody', revision=1, paid=True,
                           order_state='paid_held', attempt_state='confirmed',
                           retained_quote={'snapshot': {'buyer_fee_minor': 10,
                                                        'shipping_minor': 5, 'payable_minor': 100}})
            return dict(receipts=[receipt], journal=[dict(receipt, effect_count=1)],
                        custody=[dict(receipt, records=[{
                            'id': 'test-custody-' + reference,
                            'operations': [{'id': 'test-intake-' + reference}],
                        }])], inbox=[dict(receipt, id='test-first'),
                            dict(receipt, id='test-second')], outbox=[receipt])

        class Provider:
            def __init__(self, lose):
                self.read_count = 0
                self.lose = lose
                self.restore_references = None

            def call(self, action, request):
                result = {}
                if action == 'authoritative-reads':
                    self.read_count += 1
                    result = rows('test-baseline')
                    if self.read_count == 1 and self.lose == 'baseline-wait':
                        self.acknowledged_baseline_ids = {'test-baseline'}
                        raise Unavailable('communications-payment-confirmed-delivery')
                    if self.read_count == 1 and self.lose in ('baseline-inbox', 'baseline-outbox'):
                        name = self.lose.removeprefix('baseline-')
                        result[name] = rows('test-unrelated')[name]
                    if self.read_count > 1:
                        for name, values in rows('test-command').items():
                            result[name] += values
                        if self.lose == 'inbox':
                            result['inbox'] = result['inbox'][1:]
                        if self.lose == 'extra-inbox':
                            result['inbox'].append(result['inbox'][0])
                        if self.lose == 'extra-outbox':
                            result['outbox'].append(result['outbox'][-1])
                        if self.lose is False:
                            for name, values in rows('test-unrelated').items():
                                result[name] += values
                        if self.lose is True:
                            result['journal'][1]['amount_minor'] = 99
                            result['receipts'][1]['amount_minor'] = 99
                elif action == 'build':
                    result = dict(candidate='test-current', archive_mode='reused', artifacts={
                        name: 'test-current:' + name for name in driver.SERVICES})
                elif action == 'restart':
                    if self.lose in ('orders-restart', 'baseline-wait') and request['service'] == 'orders':
                        raise Unavailable('test-orders-restart')
                    result = dict(service=request['service'], before_pid=123, after_pid=124,
                        before_start='100', after_start='200', ready=True,
                        artifact='test-current:' + request['service'],
                        before_artifact='test-prior:' + request['service'],
                        before_orders_executable='test-prior-orders',
                        orders_executable=('test-prior-orders' if self.lose == 'shared-release'
                                           else 'test-current-orders'))
                elif action == 'recover-command':
                    assert self.lose != 'orders-restart'
                    assert request['expected_artifact'] == 'test-current:orders'
                    if self.lose == 'retry-after-ack':
                        self.acknowledged_callback_id = 'test-command'
                        raise Unavailable('test-retry-failed')
                    if self.lose in ('retry-pid', 'retry-start', 'retry-no-replacement'):
                        self.acknowledged_callback_id = 'test-command'
                    artifact = ('test-prior:orders' if self.lose == 'wrong-artifact'
                                else request['expected_artifact'])
                    result = {name: values + rows('test-command')[name]
                              for name, values in rows('test-baseline').items()}
                    result = dict(result, product_operation_ids=['test-command'],
                                  same_reference=True, response_discarded=True,
                                  artifact=artifact, before_artifact=artifact,
                                  service='orders', ready=True, before_pid=124, after_pid=125,
                                  before_start='200', after_start='300')
                    if self.lose == 'retry-pid':
                        result['before_pid'] = 126
                    if self.lose == 'retry-start':
                        result['before_start'] = '201'
                    if self.lose == 'retry-no-replacement':
                        result['after_pid'] = result['before_pid']
                elif action == 'rollback':
                    result = {name: values + rows('test-command')[name]
                              for name, values in rows('test-baseline').items()}
                    if self.lose == 'rollback-hold':
                        result['receipts'][-1] = dict(result['receipts'][-1], paid=False)
                    if self.lose == 'rollback-inbox':
                        result['inbox'] = [row for row in result['inbox']
                                           if row['operation_id'] != 'test-command']
                    if self.lose == 'rollback-economics':
                        quote = result['receipts'][-1]['retained_quote']
                        quote['snapshot'].update(buyer_fee_minor=9, shipping_minor=6)
                    result.update(previous_artifact='test-prior:orders', artifact='test-prior:orders',
                                  before_artifact='test-current:orders',
                                  before_orders_executable=('test-prior-orders' if self.lose == 'shared-release'
                                                            else 'test-current-orders'),
                                  orders_executable=('test-current-orders' if self.lose == 'same-orders'
                                                     else 'test-prior-orders'),
                                  migrations_reversed=False, ready=True, current_authority_verified=True,
                                  service='orders', before_pid=125, after_pid=126,
                                  before_start='300', after_start='400')
                    if self.lose == 'rollback-pid':
                        result['before_pid'] = 124
                    if self.lose == 'rollback-start':
                        result['before_start'] = '301'
                elif action == 'restore':
                    self.restore_references = request['acknowledged_product_ids']
                    if self.lose == 'measured-restore-loss':
                        raise driver.LostAcknowledgedOperations({'test-command', 'test-baseline'})
                    if self.lose == 'missing-restore' or not request['acknowledged_product_ids']:
                        raise Unavailable('E04-connected-backup-output')
                    expected = ['test-baseline']
                    if self.lose not in ('orders-restart', 'wrong-artifact', 'baseline-wait'):
                        expected.append('test-command')
                    assert request['acknowledged_product_ids'] == expected
                    result = {name: values + rows('test-command')[name]
                              for name, values in rows('test-baseline').items()}
                    if self.lose == 'restore-loss':
                        result['receipts'].pop()
                    if self.lose == 'restore-inbox':
                        result['inbox'] = [row for row in result['inbox']
                                           if row['operation_id'] != 'test-command']
                    if self.lose == 'restore-economics':
                        quote = result['receipts'][-1]['retained_quote']
                        quote['snapshot'].update(buyer_fee_minor=9, shipping_minor=6)
                    result.update(backup_provider='E04', backup_reference='test-backup',
                                  isolated=True, postgres_major=17, restored_domains=list(driver.DOMAINS),
                                  lost_acknowledged_operations=[], current_deletions_applied=True,
                                  current_revocations_applied=True)
                return dict(request, **result, source='native', synthetic=False,
                            seeded=False, state='passed')

        for lose in (False, 'shared-release', True, 'inbox', 'extra-inbox', 'extra-outbox'):
            result = driver.execute(Provider(lose), 'test-revision')
            replacement = next(row for row in result['results']
                               if row['scenario_id'] == 'restart/orders')
            self.assertEqual(result['build_id'], 'test-current')
            build = next(row for row in result['results'] if row['scenario_id'] == 'release-build')
            self.assertEqual(build['build_id'], result['build_id'])
            self.assertEqual(build['archive_mode'], 'reused')
            baseline = result['results'][0]
            self.assertEqual(baseline['product_operation_ids'], ['test-baseline'])
            self.assertEqual(baseline['custody_receipt_ids'], ['test-custody-test-baseline'])
            self.assertEqual(baseline['custody_operation_ids'], ['test-intake-test-baseline'])
            recovered = next(row for row in result['results']
                             if row['scenario_id'] == 'acknowledged-command')
            self.assertEqual(recovered['recovered_callback_ids'], ['test-command'])
            self.assertEqual(recovered['custody_receipt_ids'], ['test-custody-test-command'])
            self.assertEqual(replacement['before_pid'], 123)
            self.assertEqual(replacement['after_pid'], 124)
            self.assertEqual(replacement['before_start'], '100')
            self.assertEqual(replacement['after_start'], '200')
            self.assertEqual(replacement['before_artifact'], 'test-prior:orders')
            self.assertEqual(replacement['artifact'], 'test-current:orders')
            restore = next(r for r in result['results'] if r['scenario_id'] == 'restore')
            self.assertEqual(restore['backup_reference'], 'test-backup')
            self.assertEqual(restore['restored_domains'], list(driver.DOMAINS))
            self.assertEqual(restore['lost_acknowledged_operations'], [])
            self.assertTrue(restore['current_deletions_applied'] and restore['current_revocations_applied'])
            self.assertIn('restore', result['provider_evidence']['release/version-rollback-restore'])
            self.assertIn('release/version-rollback-restore: current repeated proof required',
                          result['remaining_proof'])
            self.assertFalse(result['certification_accepted'])
            final = result['results'][-1]
            self.assertEqual(final['state'], 'passed' if lose in (False, 'shared-release') else 'failed')
            if lose not in (False, 'shared-release'):
                field = {True: 'receipts', 'inbox': 'inbox', 'extra-inbox': 'inbox',
                         'extra-outbox': 'outbox'}[lose]
                self.assertEqual(final['missing_capability'], 'retained-acknowledged-' + field)


        for failure, reason in (
                ('orders-restart', 'candidate-orders-restart'),
                ('retry-pid', 'candidate-orders-process-continuity'),
                ('retry-start', 'candidate-orders-process-continuity'),
                ('retry-no-replacement', 'candidate-orders-process-continuity'),
                ('wrong-artifact', 'recovered-candidate-orders-artifact')):
            result = driver.execute(Provider(failure), 'test-revision')
            recovered = next(row for row in result['results']
                             if row['scenario_id'] == 'acknowledged-command')
            self.assertEqual(recovered['state'], 'failed')
            self.assertEqual(recovered['missing_capability'], reason)
            self.assertNotIn('release/receipt-reconciliation', result['provider_evidence'])

        provider = Provider('retry-after-ack')
        result = driver.execute(provider, 'test-revision')
        self.assertEqual(provider.restore_references, ['test-baseline', 'test-command'])
        self.assertEqual(result['state'], 'failed')
        failed = next(row for row in result['results']
                      if row['scenario_id'] == 'acknowledged-command')
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(failed['missing_capability'], 'test-retry-failed')
        self.assertEqual(failed['acknowledged_callback_ids'], ['test-command'])
        self.assertEqual(failed['product_operation_ids'], ['test-command'])
        self.assertNotIn('recovered_callback_ids', failed)
        self.assertNotIn('release/receipt-reconciliation', result['provider_evidence'])

        provider = Provider('baseline-wait')
        result = driver.execute(provider, 'test-revision')
        self.assertEqual(provider.restore_references, ['test-baseline'])
        self.assertEqual(result['results'][0]['acknowledged_baseline_ids'], ['test-baseline'])
        self.assertEqual(result['results'][0]['state'], 'failed')

        result = driver.execute(Provider('measured-restore-loss'), 'test-revision')
        restore = next(row for row in result['results'] if row['scenario_id'] == 'restore')
        self.assertEqual(restore['state'], 'failed')
        self.assertEqual(restore['missing_capability'], 'lost-acknowledged-operations')
        self.assertEqual(restore['lost_acknowledged_operations'], ['test-baseline', 'test-command'])
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('release/version-rollback-restore', result['provider_evidence'])

        for missing in ('inbox', 'outbox'):
            result = driver.execute(Provider('baseline-' + missing), 'test-revision')
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(result['results'][0]['missing_capability'],
                             'acknowledged-' + missing + '-coverage')
        for scenario, loss, expected in (
                ('rollback', 'rollback-pid', 'retry-orders-process-continuity'),
                ('rollback', 'rollback-start', 'retry-orders-process-continuity'),
                ('rollback', 'same-orders', 'orders-executable-continuity'),
                ('rollback', 'rollback-economics', 'retained-acknowledged-receipts'),
                ('rollback', 'rollback-hold', 'retained-acknowledged-receipts'),
                ('rollback', 'rollback-inbox', 'retained-acknowledged-inbox'),
                ('restore', 'restore-inbox', 'retained-acknowledged-inbox'),
                ('restore', 'restore-economics', 'retained-acknowledged-receipts'),
                ('restore', 'missing-restore', 'E04-connected-backup-output'),
                ('restore', 'restore-loss', 'retained-acknowledged-receipts')):
            result = driver.execute(Provider(loss), 'test-revision')
            self.assertEqual(result['state'], 'failed')
            failed = next(row for row in result['results'] if row['scenario_id'] == scenario)
            self.assertEqual(failed['missing_capability'], expected)
            self.assertEqual(result['results'][-1]['missing_capability'],
                             'retained-records-after-' + scenario)
            self.assertNotIn('release/receipt-reconciliation', result['provider_evidence'])


if __name__ == '__main__':
    unittest.main()


def test_retained_records_preserve_multiplicity():
    from collections import Counter
    import json
    original = [{'operation_id': 'test-operation', 'id': 'test-first'},
                {'operation_id': 'test-operation', 'id': 'test-second'}]
    def encode(rows):
        return Counter(json.dumps(r, sort_keys=True) for r in rows)

    assert encode(original) - encode(original[1:])
    assert encode(original + original) - encode(original)


def test_rehearsal_prints_only_outcome_and_keeps_references_private(tmp_path, capsys):
    import json
    import stat

    result = {'state': 'passed', 'results': [{
        'product_operation_ids': ['test-callback'],
        'custody_receipt_ids': ['test-intake-receipt'],
        'custody_operation_ids': ['test-intake-command'],
    }]}
    with patch.dict(os.environ, {'E09_MODE': 'rehearsal'}), \
            patch('sys.argv', ['launcher.py', '--run-dir', str(tmp_path)]), \
            patch('driver.socket.gethostname', return_value='beirut-test-1'), \
            patch('driver.Native'), patch('driver.execute', return_value=result), \
            patch('driver.subprocess.run'):
        assert driver.main(whole_stack=True) == 0
    assert json.loads(capsys.readouterr().out) == {'state': 'passed'}
    summary = tmp_path / 'scenarios/e09/summary.json'
    assert stat.S_IMODE(summary.stat().st_mode) == 0o600
    assert json.loads(summary.read_text()) == result


@pytest.mark.parametrize(('error', 'reason'), [
    (subprocess.TimeoutExpired(['test-private-command'], 10), 'preflight-command-timeout'),
    (subprocess.CalledProcessError(1, ['test-private-command']), 'preflight-command-failed'),
])
def test_startup_command_failure_cleans_up_and_writes_private_summary(tmp_path, capsys, error, reason):
    import json
    import stat

    with patch.dict(os.environ, {'E09_MODE': 'rehearsal'}), \
            patch('sys.argv', ['launcher.py', '--run-dir', str(tmp_path)]), \
            patch('driver.socket.gethostname', return_value='beirut-test-1'), \
            patch('driver.Native') as provider, patch('driver.subprocess.run') as revision, \
            patch('driver.execute') as execute:
        revision.return_value.stdout = 'test-revision'
        execution = provider.return_value.execution
        execution.start.side_effect = error

        assert driver.main(whole_stack=True) == 1

        execution.close.assert_called_once_with()
        execute.assert_not_called()

    output = capsys.readouterr()
    assert json.loads(output.out) == {'state': 'failed'}
    assert output.err == ''
    summary = tmp_path / 'scenarios/e09/summary.json'
    assert stat.S_IMODE(summary.stat().st_mode) == 0o600
    raw = summary.read_text()
    assert 'test-private-command' not in raw
    result = json.loads(raw)
    assert result['source_revision'] == 'test-revision'
    assert result['results'][0]['missing_capability'] == reason
    assert result['provider_evidence'] == {}
    assert result['remaining_proof']
    assert result['certification_accepted'] is False


@pytest.mark.parametrize('interruption', [False, True])
def test_failure_appends_to_measured_rehearsal_evidence(tmp_path, capsys, interruption):
    import json

    class Provider:
        acknowledged_baseline_ids = {'test-baseline'}
        acknowledged_callback_id = 'test-callback'
        partial_measurements = {}

        def call(self, action, request):
            answer = {}
            if action == 'authoritative-reads':
                if 'candidate' in request and interruption:
                    self.partial_measurements = {
                        'custody': [{'operation_id': 'test-callback', 'records': [
                            {'id': 'test-partial-custody', 'operations': [{'id': 'test-partial-intake'}]}
                        ]}]
                    }
                    raise driver.Interrupted('rehearsal-interrupted')
                answer = {'receipts': [{'operation_id': 'test-baseline'}], 'custody': [
                    {'operation_id': 'test-baseline', 'records': [
                        {'id': 'test-custody', 'operations': [{'id': 'test-intake'}]}
                    ]}
                ]}
            elif action == 'build':
                answer = dict(candidate='test-build', artifacts={
                    name: 'test-build:' + name for name in driver.SERVICES})
            elif action == 'restart':
                answer = dict(service=request['service'], before_pid=123, after_pid=124,
                              before_start='100', after_start='200', ready=True,
                              artifact='test-build:' + request['service'])
            elif action == 'restore':
                raise driver.LostAcknowledgedOperations({'test-callback'})
            else:
                raise Unavailable('test-missing-case')
            return dict(request, **answer, source='native', synthetic=False, seeded=False, state='passed')

    provider = Provider()
    provider.execution = unittest.mock.Mock()
    provider.execution.close.side_effect = Unavailable('owned-group-stop-timeout')
    with patch.dict(os.environ, {'E09_MODE': 'rehearsal'}), \
            patch('sys.argv', ['launcher.py', '--run-dir', str(tmp_path)]), \
            patch('driver.socket.gethostname', return_value='beirut-test-1'), \
            patch('driver.Native', return_value=provider), \
            patch('driver.subprocess.run', return_value=unittest.mock.Mock(stdout='test-revision')):
        assert driver.main(whole_stack=True) == 1

    assert json.loads(capsys.readouterr().out) == {'state': 'failed'}
    result = json.loads((tmp_path / 'scenarios/e09/summary.json').read_text())
    rows = {row['scenario_id']: row for row in result['results']}
    assert result['run_id']
    assert result['build_id'] == 'test-build'
    assert 'preflight' not in rows
    assert rows['baseline']['custody_receipt_ids'] == ['test-custody']
    assert rows['restart/orders']['after_pid'] == 124
    assert rows['acknowledged-command']['acknowledged_callback_ids'] == ['test-callback']
    assert rows['restore']['lost_acknowledged_operations'] == ['test-callback']
    assert rows['cleanup']['missing_capability'] == 'owned-group-stop-timeout'
    assert not result['certification_accepted']
    if interruption:
        assert rows['interruption']['missing_capability'] == 'rehearsal-interrupted'
        assert rows['reconciliation']['missing_capability'] == 'scenario-interrupted'
        assert rows['reconciliation']['custody_receipt_ids'] == ['test-partial-custody']
        assert rows['reconciliation']['custody_operation_ids'] == ['test-partial-intake']
    else:
        assert 'interruption' not in rows
