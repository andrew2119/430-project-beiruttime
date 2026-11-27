"""Run the native auction proof and write a redacted scenario summary."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time

import httpx

from contract import CASES, Dataset, EXPECTED, INVARIANTS, VERSION
from harness import summary
from native_provider import MissingCapability, NativeProvider, Replica, ROOT, private_json

# Revocation consumes one prepared session after the other scenarios use it.
SCENARIOS = ('viewers', 'bidders', 'notices',
             *(case for case in CASES if case != 'revoked_identity'), 'revoked_identity')


async def execute(run_dir):
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report = {'schema_version': VERSION, 'source': 'connected', 'source_revision': revision,
              'status': 'failed', 'scenarios': {}}
    provider = replica = None
    setup_failure = None
    try:
        inputs = private_json(run_dir / 'a10-input.json')
        replica = Replica(run_dir)
        await replica.start()
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                     limits=httpx.Limits(max_connections=250)) as client:
            provider = NativeProvider(run_dir, inputs, replica, client)
            await asyncio.wait_for(provider.prepare(), 4500)
            for name in SCENARIOS:
                started = time.monotonic()
                offset = len(provider.operations)
                row = {'state': 'failed', 'operation_ids': [], 'measured_seconds': 0,
                       'source_revision': revision}
                try:
                    dataset = Dataset()
                    if name in ('viewers', 'bidders', 'notices'):
                        rows = await asyncio.wait_for(provider.run_load(name, dataset), 480)
                        count, replicas, target = {'viewers': (50, 2, 2000),
                                                  'bidders': (200, 1, None),
                                                  'notices': (200, 1, 30000)}[name]
                        measured = summary(rows, count, replicas, target)
                        row['measurements'] = measured
                        if name == 'viewers':
                            row['observation'] = 'read_visibility_only'
                        if name == 'bidders':
                            row['business_denials'] = dict(provider.failures)
                        assert measured['errors'] == 0 and measured['target_met'] is not False
                    else:
                        result = await asyncio.wait_for(provider.exercise(name, dataset),
                                                        1600 if name in ('worker_restart_acknowledged_bids', 'after_end',
                                                                        'one_winner_allocation_restart',
                                                                        'outbox_replay_duplicate_notice') else 60)
                        assert result.state == EXPECTED.get(name, 'succeeded')
                        assert set(INVARIANTS.get(name, ())) <= set(result.invariants)
                    row['state'] = 'passed'
                except MissingCapability as error:
                    row['missing_capability'] = str(error)
                except Exception:
                    # Private response content and exception text never enter evidence.
                    row['missing_capability'] = 'request_or_durable_assertion:' + name
                row['operation_ids'] = sorted(set(
                    [result['operation_id'] for _, _, result in provider.acknowledged]
                    if name == 'notices' else provider.operations[offset:]))
                row['measured_seconds'] = time.monotonic() - started
                report['scenarios'][name] = row
    except MissingCapability as error:
        setup_failure = str(error)
    except Exception:
        setup_failure = 'native_configuration_or_authorized_scenario_stock'
    finally:
        if replica is not None:
            await replica.stop()
    for name in SCENARIOS:
        report['scenarios'].setdefault(name, {
            'state': 'failed', 'operation_ids': [], 'measured_seconds': 0,
            'source_revision': revision, 'missing_capability': setup_failure or 'scenario_not_executed'})
    if all(row['state'] == 'passed' for row in report['scenarios'].values()):
        report['status'] = 'passed'
    destination = run_dir / 'scenarios/a10'
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / 'summary.tmp'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    temporary.replace(destination / 'summary.json')
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description='Beirut Time native auction proof')
    parser.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    return asyncio.run(execute(args.run_dir.resolve()))


if __name__ == '__main__':
    raise SystemExit(main())
