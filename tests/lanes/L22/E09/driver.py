"""Bounded local release recovery rehearsal."""
import argparse
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import time
import uuid

from recovery import DOMAINS, OWNERS

SERVICES = (*DOMAINS, 'web')


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
        require(type(receipt['amount_minor']) is int, 'integer-money')
        require(receipt['currency'] == money['currency'] == 'USD'
                and receipt['amount_minor'] == money['amount_minor']
                and money['effect_count'] == 1, 'journal-reconciliation')
        require(receipt['custody_reference'] == possession['custody_reference']
                and bool(possession['custody_reference'])
                and receipt['revision'] == possession['revision'],
                'custody-reconciliation')
    return ids


class Native:
    def __init__(self, run):
        settings = run / 'native-v1.json'
        require(not settings.is_symlink() and stat.S_IMODE(settings.stat().st_mode) == 0o600,
                'private-native-settings')
        self.settings = settings
        from native import Execution
        self.execution = Execution(run, settings)

    def call(self, action, request):
        from native import Unavailable
        try:
            return self.execution.call(action, request)
        except Unavailable as error:
            raise Missing(str(error)) from None


def execute(provider, revision):
    results = []
    candidate = None
    baseline = None
    run_id = str(uuid.uuid4())

    def step(scenario, action, payload, check):
        start = time.monotonic()
        operation = str(uuid.uuid4())
        row = {'scenario_id': scenario, 'operation_ids': [operation],
               'source_revision': revision, 'owners': list(OWNERS)}
        try:
            answer = provider.call(action, {**payload, 'operation_id': operation,
                                           'source_revision': revision, 'run_id': run_id})
            require(answer.get('operation_id') == operation
                    and answer.get('source_revision') == revision
                    and answer.get('run_id') == run_id, action + '-binding')
            require(answer.get('source') == 'native' and answer.get('synthetic') is False
                    and answer.get('seeded') is False, action + '-connected-source')
            require(answer.get('state') == 'passed', action + '-outcome')
            check(answer)
            row['state'] = 'passed'
            return answer
        except (Missing, KeyError, ValueError, TypeError, OSError,
                subprocess.SubprocessError) as error:
            row.update(state='failed', missing_capability=(str(error) if isinstance(error, Missing)
                                                          else action + '-capability'))
            return None
        finally:
            row['seconds'] = round(time.monotonic() - start, 6)
            results.append(row)

    def snapshot(answer):
        reconcile_reads(answer['receipts'], answer['journal'], answer['custody'])

    baseline = step('baseline', 'authoritative-reads', {}, snapshot)
    built = step('release-build', 'build', {'services': list(SERVICES)},
                 lambda a: require(set(a['artifacts']) == set(SERVICES)
                                   and all(a['artifacts'].values())
                                   and bool(a['candidate']), 'ten-release-artifacts'))
    if built:
        candidate = built['candidate']
        for service in SERVICES:
            step('restart/' + service, 'restart', {'service': service, 'candidate': candidate},
                 lambda a, expected=service: require(a['service'] == expected
                                   and type(a['before_pid']) is int
                                   and type(a['after_pid']) is int
                                   and a['before_pid'] > 1 and a['after_pid'] > 1
                                   and a['before_pid'] != a['after_pid']
                                   and a['before_start'] != a['after_start']
                                   and a['artifact'] == built['artifacts'][a['service']]
                                   and a['ready'] is True, 'release-process-readiness'))
        step('rollback', 'rollback', {'service': 'orders', 'candidate': candidate},
             lambda a: require(bool(a['previous_artifact'])
                               and a['artifact'] == a['previous_artifact']
                               and a['artifact'] != built['artifacts']['orders']
                               and a['migrations_reversed'] is False
                               and a['ready'] is True, 'compatible-prior-release'))
        step('restore', 'restore', {'backup_provider': 'E04', 'isolated': True},
             lambda a: require(a['backup_provider'] == 'E04' and bool(a['backup_reference'])
                               and a['isolated'] is True and a['postgres_major'] == 17
                               and set(a['restored_domains']) == set(DOMAINS)
                               and a['lost_acknowledged_operations'] == []
                               and a['current_deletions_applied'] is True
                               and a['current_revocations_applied'] is True,
                               'E04-connected-backup-restore'))
        def retained(answer):
            snapshot(answer)
            require(baseline is not None, 'connected-baseline')
            original = {r['operation_id']: r for r in baseline['receipts']}
            current = {r['operation_id']: r for r in answer['receipts']}
            require(all(current.get(k) == v for k, v in original.items()),
                    'retained-acknowledged-receipts')
        step('reconciliation', 'authoritative-reads', {'candidate': candidate}, retained)
    else:
        for scenario in [*('restart/' + s for s in SERVICES), 'rollback', 'restore', 'reconciliation']:
            results.append({'scenario_id': scenario, 'state': 'failed', 'operation_ids': [],
                            'seconds': 0, 'source_revision': revision, 'owners': list(OWNERS),
                            'missing_capability': 'connected-baseline-and-release-build'})
    return {'schema_version': 'L22.E09.driver.v1', 'source_revision': revision,
            'run_id': run_id, 'results': results,
            'state': 'passed' if all(r['state'] == 'passed' for r in results) else 'failed'}


def main():
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
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True,
                              capture_output=True, text=True).stdout.strip()
    try:
        require(socket.gethostname().split('.')[0] == 'beirut-test-1', 'beirut-test-1-host')
        result = execute(Native(run), revision)
    except (Missing, OSError, KeyError, ValueError, TypeError) as error:
        reason = str(error) if isinstance(error, Missing) else 'native-settings-release-adapter'
        result = {'source_revision': revision, 'state': 'failed', 'results': [{
            'scenario_id': 'preflight', 'state': 'failed', 'operation_ids': [], 'seconds': 0,
            'source_revision': revision, 'missing_capability': reason}]}
    temporary = output / 'summary.tmp'
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(output / 'summary.json')
    print(json.dumps(result))
    return 0 if result['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
