"""Bounded local release recovery rehearsal."""
from collections import Counter
import argparse
from http.client import HTTPException
import json
import os
from pathlib import Path
import socket
import signal
import stat
import subprocess
import tempfile
import time
import uuid

from native import Unavailable
from recovery import DOMAINS, OWNERS, REHEARSAL_SCENARIOS, SERVICES, process_transition, provider_evidence
from restore import LostAcknowledgedOperations

class Interrupted(Exception):
    """End the rehearsal immediately and clean up owned children."""


class Missing(ValueError):
    """A required connected capability is absent or invalid."""


def require(condition, name):
    if not condition:
        raise Missing(name)


def reconcile_reads(receipts, journal, custody):
    require(bool(receipts), 'acknowledged-operation-reads')
    ids = [r['operation_id'] for r in receipts]
    require(len(ids) == len(set(ids)), 'unique-operation-receipts')
    for rows, name in ((journal, 'journal'), (custody, 'custody')):
        require(len(rows) == len(ids), name + '-coverage')
        require({r['operation_id'] for r in rows} == set(ids), name + '-coverage')
    for receipt in receipts:
        operation = receipt['operation_id']
        money = next(r for r in journal if r['operation_id'] == operation)
        possession = next(r for r in custody if r['operation_id'] == operation)
        require(receipt.get('paid') is True
                and receipt.get('order_state') == 'paid_held'
                and receipt.get('attempt_state') == 'confirmed', 'current-held-payment')
        require(type(receipt['amount_minor']) is int, 'integer-money')
        require(receipt['currency'] == money['currency'] == 'USD'
                and receipt['amount_minor'] == money['amount_minor']
                and money['effect_count'] == 1, 'journal-reconciliation')
        require(receipt['custody_reference'] == possession['custody_reference']
                and bool(possession['custody_reference'])
                and receipt['revision'] == possession['revision'],
                'custody-reconciliation')
    return ids


def reconcile_snapshot(answer):
    ids = reconcile_reads(answer['receipts'], answer['journal'], answer['custody'])
    for name in ('outbox', 'inbox'):
        require(set(ids).issubset(row['operation_id'] for row in answer[name]),
                'acknowledged-' + name + '-coverage')
    return ids


class Native:
    def __init__(self, run, whole_stack=False):
        settings = run / 'native-v1.json'
        require(not settings.is_symlink() and stat.S_IMODE(settings.stat().st_mode) == 0o600,
                'private-native-settings')
        self.settings = settings
        from native import Execution
        if whole_stack:
            from launcher import WholeStack
            Execution = WholeStack
        self.execution = Execution(run, settings)

    @property
    def acknowledged_callback_id(self):
        return self.execution.acknowledged_callback_id

    @property
    def acknowledged_baseline_ids(self):
        return self.execution.acknowledged_baseline_ids

    @property
    def partial_measurements(self):
        return self.execution.partial_measurements

    def call(self, action, request):
        self.execution.partial_measurements.clear()
        return self.execution.call(action, request)


def record_measurements(row, answer, action, *, callback=None):
    if 'receipts' in answer:
        row['product_operation_ids'] = [receipt['operation_id'] for receipt in answer['receipts']]
    if 'lost_acknowledged_operations' in answer:
        row['lost_acknowledged_operations'] = answer['lost_acknowledged_operations']
    if 'product_operation_ids' in answer:
        row['recovered_callback_ids'] = answer['product_operation_ids']
    if 'custody' in answer:
        custody_rows = answer['custody']
        if action == 'recover-command':
            recovered_ids = {callback} if callback else set(answer.get('product_operation_ids', ()))
            custody_rows = [custody for custody in custody_rows
                            if custody['operation_id'] in recovered_ids]
        row['custody_receipt_ids'] = sorted({
            fact['id'] for custody in custody_rows
            for fact in custody['records']
        })
        row['custody_operation_ids'] = sorted({
            operation['id'] for custody in custody_rows
            for fact in custody['records'] for operation in fact['operations']
        })
    for field in ('service', 'before_pid', 'after_pid', 'before_start',
                  'after_start', 'before_artifact', 'artifact',
                  'previous_artifact', 'ready', 'migrations_reversed', 'current_authority_verified',
                  'before_orders_executable', 'orders_executable',
                  'same_reference', 'response_discarded'):
        if field in answer:
            value = answer[field]
            require(type(value) in (str, int, bool)
                    and (not isinstance(value, str) or len(value) <= 512),
                    'bounded-replacement-result')
            row[field] = value


def new_summary(revision):
    return {'schema_version': 'L22.E09.driver.v1', 'source_revision': revision,
            'run_id': str(uuid.uuid4()), 'build_id': None, 'results': []}


def require_orders_transition(previous, current, reason):
    require(previous is not None and process_transition(current, 'orders')
            and current['before_pid'] == previous['after_pid']
            and current['before_start'] == previous['after_start'], reason)


def execute(provider, revision, *, summary=None):
    if summary is None:
        summary = new_summary(revision)
    results = summary['results']
    candidate = None
    baseline_references = set()
    run_id = summary['run_id']

    def step(scenario, action, payload, check):
        start = time.monotonic()
        operation = str(uuid.uuid4())
        row = {'scenario_id': scenario, 'operation_ids': [operation],
               'source_revision': revision, 'owners': list(OWNERS),
               'state': 'failed', 'missing_capability': 'scenario-incomplete'}
        results.append(row)
        try:
            answer = provider.call(action, {**payload, 'operation_id': operation,
                                           'source_revision': revision, 'run_id': run_id})
            require(answer.get('operation_id') == operation
                    and answer.get('source_revision') == revision
                    and answer.get('run_id') == run_id, action + '-binding')
            require(answer.get('source') == 'native' and answer.get('synthetic') is False
                    and answer.get('seeded') is False, action + '-connected-source')
            require(answer.get('state') == 'passed', action + '-outcome')
            if scenario == 'baseline':
                baseline_references.update(receipt['operation_id'] for receipt in answer['receipts'])
            record_measurements(row, answer, action)
            if action == 'build':
                row['build_id'] = answer['candidate']
                if 'archive_mode' in answer:
                    row['archive_mode'] = answer['archive_mode']
            if action == 'restore':
                for key in ('backup_provider', 'backup_reference', 'isolated', 'postgres_major',
                            'restored_domains', 'lost_acknowledged_operations',
                            'current_deletions_applied', 'current_revocations_applied'):
                    row[key] = answer[key]
            check(answer)
            if action == 'build':
                summary['build_id'] = answer['candidate']
            row['state'] = 'passed'
            del row['missing_capability']
            return answer
        except Interrupted:
            row.update(state='failed', missing_capability='scenario-interrupted')
            raise
        except LostAcknowledgedOperations as error:
            row.update(state='failed', missing_capability=str(error),
                       lost_acknowledged_operations=error.references)
            return None
        except (Missing, HTTPException, KeyError, ValueError, TypeError, OSError,
                subprocess.SubprocessError) as error:
            row.update(state='failed', missing_capability=(str(error) if isinstance(error, (Missing, Unavailable))
                                                          else action + '-capability'))
            return None
        finally:
            if row['state'] != 'passed':
                partial = getattr(provider, 'partial_measurements', None)
                if partial:
                    measured = {}
                    record_measurements(measured, partial, action,
                                        callback=getattr(provider, 'acknowledged_callback_id', None))
                    for field, value in measured.items():
                        row.setdefault(field, value)
            if scenario == 'baseline':
                baseline_references.update(getattr(provider, 'acknowledged_baseline_ids', ()))
                if baseline_references:
                    row['acknowledged_baseline_ids'] = sorted(baseline_references)
                    row.setdefault('product_operation_ids', sorted(baseline_references))
            if action == 'recover-command':
                acknowledged = getattr(provider, 'acknowledged_callback_id', None)
                if acknowledged:
                    row['acknowledged_callback_ids'] = [acknowledged]
                    if row.get('state') != 'passed':
                        row.setdefault('product_operation_ids', [acknowledged])
            row['seconds'] = round(time.monotonic() - start, 6)

    baseline = step('baseline', 'authoritative-reads', {}, reconcile_snapshot)
    built = step('release-build', 'build', {'services': list(SERVICES)},
                 lambda a: require(set(a['artifacts']) == set(SERVICES)
                                   and all(a['artifacts'].values())
                                   and bool(a['candidate']), 'ten-release-artifacts'))
    if built:
        candidate = built['candidate']
        restarts = {}
        for service in SERVICES:
            restarts[service] = step('restart/' + service, 'restart', {'service': service, 'candidate': candidate},
                 lambda a, expected=service: require(a['service'] == expected
                                   and type(a['before_pid']) is int
                                   and type(a['after_pid']) is int
                                   and a['before_pid'] > 1 and a['after_pid'] > 1
                                   and a['before_pid'] != a['after_pid']
                                   and a['before_start'] != a['after_start']
                                   and a['artifact'] == built['artifacts'][a['service']]
                                   and a['ready'] is True, 'release-process-readiness'))
        orders_artifact = built['artifacts']['orders']

        def recovered(answer):
            require(answer.get('artifact') == answer.get('before_artifact') == orders_artifact,
                    'recovered-candidate-orders-artifact')
            require_orders_transition(restarts['orders'], answer, 'candidate-orders-process-continuity')
            ids = reconcile_snapshot(answer)
            require(bool(answer['product_operation_ids'])
                    and set(answer['product_operation_ids']).issubset(ids)
                    and answer['same_reference'] is True
                    and answer['response_discarded'] is True,
                    'acknowledged-product-recovery')
        if restarts['orders'] is not None:
            recovered_state = step('acknowledged-command', 'recover-command',
                                   {'expected_artifact': orders_artifact}, recovered)
        else:
            recovered_state = None
            results.append({'scenario_id': 'acknowledged-command', 'state': 'failed',
                            'operation_ids': [], 'seconds': 0, 'source_revision': revision,
                            'owners': list(OWNERS), 'missing_capability': 'candidate-orders-restart'})

        def rollback(answer):
            restart = restarts['orders'] or {}
            prior_inputs = answer.get('orders_executable')
            candidate_inputs = answer.get('before_orders_executable')
            require(bool(prior_inputs) and bool(candidate_inputs)
                    and prior_inputs == restart.get('before_orders_executable')
                    and candidate_inputs == restart.get('orders_executable'),
                    'orders-executable-continuity')
            require(bool(answer['previous_artifact'])
                    and answer['artifact'] == answer['previous_artifact']
                    and answer['artifact'] == restart.get('before_artifact')
                    and answer.get('before_artifact') == orders_artifact
                    and answer['artifact'] != built['artifacts']['orders']
                    and answer['migrations_reversed'] is False
                    and answer['ready'] is True
                    and answer['current_authority_verified'] is True, 'compatible-prior-release')
            require_orders_transition(recovered_state, answer, 'retry-orders-process-continuity')
            retained(answer)

        def retained(answer):
            require(baseline is not None, 'connected-baseline')
            require(recovered_state is not None, 'connected-recovered-command')
            baseline_ids = {row['operation_id'] for row in baseline['receipts']}
            recovered_ids = set(recovered_state['product_operation_ids'])
            require(not (baseline_ids & recovered_ids), 'fresh-product-command-reference')
            for state, ids in ((baseline, baseline_ids), (recovered_state, recovered_ids)):
                for name in ('receipts', 'journal', 'custody', 'inbox', 'outbox'):
                    original = Counter(json.dumps(r, sort_keys=True) for r in state[name]
                                       if r['operation_id'] in ids)
                    current = Counter(json.dumps(r, sort_keys=True) for r in answer[name]
                                      if r['operation_id'] in ids)
                    require(original == current,
                            'retained-acknowledged-' + name)
            reconcile_snapshot(answer)
        rolled_back = step('rollback', 'rollback', {'service': 'orders', 'candidate': candidate}, rollback)
        acknowledged = baseline_references.copy()
        if recovered_state is not None:
            acknowledged.update(recovered_state['product_operation_ids'])
        callback = getattr(provider, 'acknowledged_callback_id', None)
        if callback:
            acknowledged.add(callback)
        references = sorted(acknowledged)

        def restored(a):
            require(bool(references)
                    and a['backup_provider'] == 'E04' and isinstance(a['backup_reference'], str)
                    and 0 < len(a['backup_reference']) <= 512
                    and len(a['restored_domains']) == len(DOMAINS)
                    and a['isolated'] is True and a['postgres_major'] == 17
                    and set(a['restored_domains']) == set(DOMAINS)
                    and a['lost_acknowledged_operations'] == []
                    and a['current_deletions_applied'] is True
                    and a['current_revocations_applied'] is True,
                    'E04-connected-backup-restore')
            retained(a)

        restore_result = step('restore', 'restore', {'backup_provider': 'E04', 'isolated': True,
                                                    'acknowledged_product_ids': references}, restored)

        def final_reconciliation(answer):
            retained(answer)
            require(rolled_back is not None, 'retained-records-after-rollback')
            require(restore_result is not None, 'retained-records-after-restore')

        step('reconciliation', 'authoritative-reads', {'candidate': candidate}, final_reconciliation)
    else:
        for scenario in REHEARSAL_SCENARIOS[2:]:
            results.append({'scenario_id': scenario, 'state': 'failed', 'operation_ids': [],
                            'seconds': 0, 'source_revision': revision, 'owners': list(OWNERS),
                            'missing_capability': 'connected-baseline-and-release-build'})
    summary.update(provider_evidence(results, revision, candidate),
                   state='passed' if all(r['state'] == 'passed' for r in results) else 'failed')
    return summary


FAILURES = (Interrupted, HTTPException, OSError, KeyError, ValueError, TypeError,
            subprocess.SubprocessError)


def record_failure(summary, scenario, reason):
    summary['results'].append({
        'scenario_id': scenario, 'state': 'failed', 'operation_ids': [], 'seconds': 0,
        'source_revision': summary['source_revision'], 'missing_capability': reason,
    })
    summary.update(provider_evidence(summary['results'], summary['source_revision'],
                                     summary['build_id']), state='failed')


def main(whole_stack=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    mode = os.environ.get('E09_MODE', 'rehearsal')
    if mode == 'railway':
        for service in SERVICES:
            print('railway up --service ' + service + ' --detach')
        print('railway rollback --service orders')
        return 0
    require(mode == 'rehearsal', 'supported-mode')
    run = args.run_dir.resolve()
    require(not run.is_relative_to(Path(__file__).resolve().parents[4]),
            'evidence-outside-source-checkout')
    output = run / 'scenarios/e09'
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = new_summary(None)
    provider = None
    phase = 'preflight'

    def interrupted(number, frame):
        raise Interrupted('rehearsal-interrupted')

    handlers = {number: signal.signal(number, interrupted)
                for number in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)}
    signal.alarm(1800)
    try:
        try:
            revision = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True, timeout=30,
                                      capture_output=True, text=True).stdout.strip()
            result['source_revision'] = revision
            require(socket.gethostname().split('.')[0] == 'beirut-test-1', 'beirut-test-1-host')
            provider = Native(run, whole_stack=whole_stack)
            provider.execution.start()
            phase = 'rehearsal'
            result = execute(provider, revision, summary=result)
        finally:
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(handlers))
            try:
                signal.alarm(0)
                if provider is not None:
                    try:
                        provider.execution.close()
                    except FAILURES as error:
                        reason = str(error) if isinstance(error, Unavailable) else 'owned-stack-cleanup'
                        record_failure(result, 'cleanup', reason)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    except FAILURES as error:
        if isinstance(error, Interrupted):
            record_failure(result, 'interruption', str(error))
        else:
            if isinstance(error, (Missing, Unavailable)):
                reason = str(error)
            elif isinstance(error, subprocess.TimeoutExpired):
                reason = phase + '-command-timeout'
            elif isinstance(error, subprocess.SubprocessError):
                reason = phase + '-command-failed'
            else:
                reason = ('native-settings-release-adapter' if phase == 'preflight'
                          else 'rehearsal-execution')
            record_failure(result, phase, reason)
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
    with tempfile.NamedTemporaryFile(mode='w', dir=output, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(result, indent=2) + '\n')
            stream.close()
            temporary.replace(output / 'summary.json')
        finally:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'state': result['state']}))
    return 0 if result['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
