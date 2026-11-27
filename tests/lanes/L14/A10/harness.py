"""Bounded separate-release runner and strict observation validation."""
import asyncio
import math
from dataclasses import asdict

from contract import CASES, EXPECTED, INVARIANTS, VERSION, Dataset, Provider, Sample


def summary(samples: list[Sample], count: int, replicas: int, target_ms=None):
    if len(samples) != count * replicas:
        raise ValueError('Incomplete observation coverage')
    expected = {(participant, replica) for participant in range(count)
                for replica in range(replicas)}
    if {(row.participant, row.replica) for row in samples} != expected:
        raise ValueError('Duplicate or missing participant observation')
    for row in samples:
        if (type(row.elapsed_ms) not in (int, float) or not math.isfinite(row.elapsed_ms)
                or row.elapsed_ms < 0 or type(row.error) is not bool
                or type(row.sequence) is not int or row.sequence < 1):
            raise ValueError('Invalid measurement')
    values = sorted(row.elapsed_ms for row in samples if not row.error)
    def percentile(p):
        return values[math.ceil(len(values) * p) - 1] if values else None
    errors = sum(row.error for row in samples)
    return {'samples': len(samples), 'errors': errors, 'p50_ms': percentile(.5),
            'p95_ms': percentile(.95), 'target_ms': target_ms,
            'target_met': None if target_ms is None else
                errors == 0 and all(row.elapsed_ms <= target_ms for row in samples)}


async def run(provider: Provider, *, clearance=False, connected=False, connection=None):
    # This runner is deliberately unavailable on the preparation server.
    if clearance is not True:
        raise PermissionError('Separate-machine release clearance required')
    if type(connected) is not bool or (connected and (
            not isinstance(connection, str) or not connection.strip() or len(connection) > 200)):
        raise ValueError('A bounded non-private connection description is required')
    dataset = Dataset()
    result = {'schema_version': VERSION, 'dataset': asdict(dataset),
              'status': 'failed', 'source': 'connected' if connected else 'synthetic_fixture',
              'connection': connection if connected else None,
              'results': {}, 'remaining_proof': []}
    async def bounded(call):
        return await asyncio.wait_for(call, timeout=dataset.timeout_seconds)
    for kind, count, replicas, target in (
        ('viewers', 50, 2, 2000), ('bidders', 200, 1, None),
        ('notices', 200, 1, 30000),
    ):
        try:
            rows = await bounded(provider.run_load(kind, dataset))
            result['results'][kind] = summary(rows, count, replicas, target)
        except (TimeoutError, ValueError, AssertionError, OSError, RuntimeError):
            result['results'][kind] = {'state': 'failed'}
            result['remaining_proof'].append(kind)
    for case in CASES:
        try:
            observation = await bounded(provider.exercise(case, dataset))
            if observation.state != EXPECTED.get(case, 'succeeded'):
                raise ValueError('Unexpected case result')
            if not set(INVARIANTS.get(case, ())).issubset(observation.invariants):
                raise ValueError('Missing durable assertion')
            result['results'][case] = {'state': 'passed'}
        except (TimeoutError, ValueError, AssertionError, OSError, RuntimeError):
            result['results'][case] = {'state': 'failed'}
            result['remaining_proof'].append(case)
    for kind in ('viewers', 'bidders', 'notices'):
        measured = result['results'][kind]
        if measured.get('errors', 1) or measured.get('target_met') is False:
            if kind not in result['remaining_proof']:
                result['remaining_proof'].append(kind)
    if not result['remaining_proof']:
        result['status'] = 'passed' if connected else 'preparation_passed'
    if not connected:
        result['remaining_proof'] += ['connected:' + name for name in
                                     ('viewers', 'bidders', 'notices', *CASES)]
    if result['status'] == 'failed':
        result['next_action'] = 'Correct failed cases and rerun the same dataset'
    return result
