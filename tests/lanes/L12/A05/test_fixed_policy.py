"""Pure policy checks; no admission, allocation or financial authority is simulated."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from bt_contracts.auction.policy.models import AcceptedBidPolicy, ReserveBasis
from bt_runtime.modules import Module


@pytest.fixture
def policy():
    root = Path('services/auction/modules/extension-policy').resolve()
    return Module('L12.extension-policy', root, (), (), None, {}, {}, ())


@pytest.mark.parametrize('remaining', [120, 90, .001, 0, -.001])
@pytest.mark.parametrize('stored', ['none.v1', 'last-two-minutes.v1'])
def test_original_end_wins_over_retained_end(policy, remaining, stored):
    end = datetime(2026, 11, 16, 18, tzinfo=timezone.utc)
    state = {'ends_at': end + timedelta(minutes=5), 'scheduled_ends_at': end,
             'server_time': end - timedelta(seconds=remaining), 'end_version': 7,
             'extension_policy': stored}
    before = state.copy()
    apply = policy.load('policy.py:accepted_bid')
    if remaining <= 0:
        with pytest.raises(ValueError):
            apply(state)
    else:
        expected = {'ends_at': end.isoformat().replace('+00:00', 'Z'),
                    'end_version': 7, 'extended': False}
        assert apply(state) == expected
        assert apply(state) == expected
    assert state == before


@pytest.mark.parametrize('current,reserve,sequence,met', [
    (430000, 450000, 2, False), (449999, 450000, 2, False),
    (450000, 450000, 2, True), (450001, 450000, 2, True),
    (450000, 450000, 0, False), (400000, None, 1, True),
    (400000, None, 0, False), (0, None, 1, False),
])
def test_reserve_public_basis(policy, current, reserve, sequence, met):
    assert policy.load('policy.py:reserve_met')(
        current_minor=current, reserve_minor=reserve, accepted_sequence=sequence) is met


@pytest.mark.parametrize('change', [
    {'current_minor': True}, {'current_minor': 450000.0}, {'current_minor': -1},
    {'reserve_minor': 0}, {'reserve_minor': False}, {'accepted_sequence': -1},
    {'accepted_sequence': True}, {'current_minor': 9_000_000_000_000_001},
])
def test_invalid_reserve_basis_fails_closed(policy, change):
    basis = {'current_minor': 450000, 'reserve_minor': 450000, 'accepted_sequence': 1, **change}
    with pytest.raises(ValidationError):
        policy.load('policy.py:reserve_met')(**basis)


def test_private_ceiling_is_not_an_input():
    with pytest.raises(ValidationError):
        ReserveBasis(current_minor=430000, reserve_minor=450000, accepted_sequence=2,
                     private_ceiling_minor=500000)


def test_contract_reserve_fixtures(policy):
    fixtures = json.loads(Path('packages/contracts-auction/policy/fixtures.json').read_text())
    for case in fixtures['reserve_basis']:
        if 'error' in case:
            with pytest.raises(ValidationError):
                ReserveBasis.model_validate(case['input'])
        else:
            assert policy.load('policy.py:reserve_met')(**case['input']) is case['result']


def test_naive_original_deadline_is_refused():
    with pytest.raises(ValidationError):
        AcceptedBidPolicy(ends_at='2026-11-16T18:00:00Z',
                          scheduled_ends_at='2026-11-16T18:00:00',
                          server_time='2026-11-16T17:59:59Z', end_version=1)
