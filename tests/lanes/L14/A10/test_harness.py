"""Synthetic runner checks only; no connected or latency acceptance."""
import asyncio
from dataclasses import replace

import pytest

from contract import CASES, EXPECTED, INVARIANTS, CaseResult, Dataset, Sample
from harness import run, summary


class FixtureProvider:
    def __init__(self):
        self.calls = []

    async def run_load(self, kind, dataset):
        self.calls.append(kind)
        count, replicas = (50, 2) if kind == 'viewers' else (200, 1)
        return [Sample(person, replica, 1, 10)
                for person in range(count) for replica in range(replicas)]

    async def exercise(self, case, dataset):
        self.calls.append(case)
        return CaseResult(EXPECTED.get(case, 'succeeded'), INVARIANTS.get(case, ()))


def test_clearance_precedes_any_work():
    provider = FixtureProvider()
    with pytest.raises(PermissionError):
        asyncio.run(run(provider))
    assert not provider.calls


def test_deterministic_fixture_covers_manifest_without_certifying_connections():
    provider = FixtureProvider()
    result = asyncio.run(run(provider, clearance=True))
    assert provider.calls == ['viewers', 'bidders', 'notices', *CASES]
    assert result['status'] == 'preparation_passed'
    assert result['source'] == 'synthetic_fixture'
    assert 'connected:viewers' in result['remaining_proof']
    assert result['results']['viewers']['samples'] == 100
    assert result['dataset'] == vars(Dataset())


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1, True])
def test_invalid_elapsed_rejected(bad):
    with pytest.raises(ValueError):
        summary([Sample(0, 0, 1, bad)], 1, 1)


def test_exact_percentiles_and_target_boundary():
    rows = [Sample(i, 0, i + 1, i + 1) for i in range(100)]
    result = summary(rows, 100, 1, 100)
    assert (result['p50_ms'], result['p95_ms'], result['target_met']) == (50, 95, True)
    assert summary(rows, 100, 1, 99)['target_met'] is False
    rows[0] = replace(rows[0], error=True)
    assert summary(rows, 100, 1, 100)['errors'] == 1
    assert summary(rows, 100, 1, 100)['target_met'] is False


@pytest.mark.parametrize('rows', [[], [Sample(0, 0, 1, 1)] * 2,
                                   [Sample(0, 0, 1, 1), Sample(0, 2, 1, 1)]])
def test_missing_duplicate_and_wrong_replica_rejected(rows):
    with pytest.raises(ValueError):
        summary(rows, 1, 2)


@pytest.mark.parametrize('case', CASES)
def test_missing_case_assertion_or_wrong_state_cannot_pass(case):
    class Broken(FixtureProvider):
        async def exercise(self, name, dataset):
            if name == case:
                return CaseResult('unavailable', ())
            return await super().exercise(name, dataset)
    result = asyncio.run(run(Broken(), clearance=True, connected=True, connection='local test fixture'))
    assert result['status'] == 'failed'
    assert case in result['remaining_proof']


def test_slow_viewer_and_notice_are_measured_failures():
    class Slow(FixtureProvider):
        async def run_load(self, kind, dataset):
            rows = await super().run_load(kind, dataset)
            rows[-1] = replace(rows[-1], elapsed_ms=30001)
            return rows
    result = asyncio.run(run(Slow(), clearance=True, connected=True, connection='local test fixture'))
    assert result['remaining_proof'] == ['viewers', 'notices']
    assert result['results']['bidders']['target_met'] is None


def test_missing_restart_assertion_fails():
    class Missing(FixtureProvider):
        async def exercise(self, case, dataset):
            observed = await super().exercise(case, dataset)
            return replace(observed, invariants=())
    result = asyncio.run(run(Missing(), clearance=True, connected=True, connection='local test fixture'))
    assert set(INVARIANTS) <= set(result['remaining_proof'])


def test_timeout_is_bounded_and_remaining(monkeypatch):
    import harness
    real_wait = asyncio.wait_for
    async def short_wait(call, timeout):
        return await real_wait(call, timeout=.01)
    monkeypatch.setattr(harness.asyncio, 'wait_for', short_wait)
    class Timeout(FixtureProvider):
        async def exercise(self, case, dataset):
            if case == 'timeout_pending':
                await asyncio.Event().wait()
            return await super().exercise(case, dataset)
    result = asyncio.run(run(Timeout(), clearance=True, connected=True, connection='local test fixture'))
    assert result['remaining_proof'] == ['timeout_pending']
