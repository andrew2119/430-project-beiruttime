"""Frozen Auction proxy v1 fixture proofs; no persisted winning bids are seeded."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import json
import random
import pytest

ROOT = next((p for p in Path(__file__).resolve().parents if (p / 'services').is_dir()), Path('/app'))
MODULE = ROOT / 'services/auction/modules/proxy/proxy.py'
if not MODULE.exists():
    MODULE = Path('/app/modules/proxy/proxy.py')
spec = importlib.util.spec_from_file_location('l06_proxy_calculation', MODULE)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
calculate = proxy.calculate


def state():
    return dict(opening_minor=10000, current_minor=10000, sequence=0,
                increment_bands=[{'from_minor': 0, 'step_minor': 1000}], leader_id=None, maxima=[])


def bid(s, bidder, amount, sequence, kind='maximum'):
    result = calculate(s, dict(bidder_id=bidder, amount_minor=amount, sequence=sequence, kind=kind))
    return {**s, **result, 'sequence': sequence}


def test_serialized_frozen_contract_fixture():
    fixture = ROOT / 'packages/contracts-auction/proxy/fixtures/competition.v1.json'
    if not fixture.exists():
        fixture = Path('/opt/domain-contracts/bt_contracts/auction/proxy/fixtures/competition.v1.json')
    case = json.loads(fixture.read_text())
    assert calculate(case['state'], case['command']) == case['result']


def test_declared_fixture_and_private_cap_raises_have_no_public_transition():
    s = bid(state(), 'A', 20000, 1)
    assert (s['leader_id'], s['current_minor']) == ('A', 10000)
    assert s['bids'] == [{'bidder_id': 'A', 'amount_minor': 10000, 'automatic': True}]
    s = bid(s, 'B', 15000, 2)
    assert (s['leader_id'], s['current_minor']) == ('A', 16000)
    assert s['bids'] == [{'bidder_id': 'A', 'amount_minor': 16000, 'automatic': True}]
    s = bid(s, 'B', 20000, 3)
    assert (s['leader_id'], s['current_minor']) == ('A', 20000)
    s = bid(s, 'B', 22000, 4)
    assert (s['leader_id'], s['current_minor']) == ('B', 21000)
    s = bid(s, 'B', 25000, 5)
    assert s['current_minor'] == 21000 and s['bids'] == []


def test_acceptance_manual_bid_competes_against_private_cap():
    s = dict(opening_minor=400000, current_minor=400000, sequence=0,
             increment_bands=[{'from_minor': 0, 'step_minor': 10000}], leader_id=None, maxima=[])
    s = bid(s, 'A', 450000, 1)
    s = bid(s, 'B', 420000, 2, 'manual')
    assert (s['leader_id'], s['current_minor']) == ('A', 430000)
    assert s['bids'] == [{'bidder_id': 'B', 'amount_minor': 420000, 'automatic': False},
                         {'bidder_id': 'A', 'amount_minor': 430000, 'automatic': True}]


def test_manual_bid_floor_and_no_self_competition():
    s = bid(state(), 'A', 18000, 1, 'manual')
    assert s['current_minor'] == 18000
    s = bid(s, 'A', 25000, 2)
    assert s['current_minor'] == 18000
    s = bid(s, 'B', 30000, 3, 'manual')
    assert (s['leader_id'], s['current_minor']) == ('B', 30000)


def test_manual_bid_does_not_reduce_an_existing_private_ceiling():
    s = bid(state(), 'A', 20000, 1)
    s = bid(s, 'A', 15000, 2, 'manual')
    assert s['current_minor'] == 15000
    assert s['maxima'] == [{'bidder_id': 'A', 'amount_minor': 20000, 'sequence': 1}]


def test_equal_caps_use_sequence_that_established_the_cap():
    s = bid(state(), 'A', 20000, 1)
    s = bid(s, 'B', 30000, 2)
    s = bid(s, 'A', 30000, 3)
    assert s['leader_id'] == 'B'


def test_increment_band_before_equal_after_and_exact_maximum_bound():
    s = state()
    s['increment_bands'].append({'from_minor': 15000, 'step_minor': 2000})
    for rival, expected in [(14999, 15999), (15000, 17000), (15001, 17001)]:
        first = bid(s, 'A', 25000, 1)
        result = bid(first, 'B', rival, 2)
        assert result['current_minor'] == expected
    result = bid(bid(s, 'A', 16000, 1), 'B', 15000, 2)
    assert result['current_minor'] == 16000  # Never round above the winning cap.


def test_inputs_unchanged():
    s = bid(state(), 'A', 20000, 1)
    before = deepcopy(s)
    bid(s, 'B', 15000, 2)
    assert s == before


@pytest.mark.parametrize('amount', [True, 1.2, '20000', -1, 0, proxy.MAX_MINOR + 1])
def test_exact_finite_minor_units_only(amount):
    with pytest.raises(ValueError):
        bid(state(), 'A', amount, 1)


def test_refuse_below_next_bid_lowering_and_non_authoritative_sequence():
    s = bid(state(), 'A', 20000, 1)
    for bidder, amount, seq in [('B', 10999, 2), ('A', 19000, 2), ('A', 20000, 2), ('B', 25000, 1)]:
        with pytest.raises(ValueError):
            bid(s, bidder, amount, seq)


def test_competing_caps_invariants_under_repeated_increases():
    rng = random.Random(6)
    for _ in range(100):
        s = state()
        for sequence in range(1, 100):
            bidder = str(rng.randrange(8))
            existing = next((m['amount_minor'] for m in s['maxima'] if m['bidder_id'] == bidder), 0)
            amount = max(existing + 1, s['current_minor'] + 1000) + rng.randrange(20000)
            old_price = s['current_minor']
            s = bid(s, bidder, amount, sequence, rng.choice(['manual', 'maximum']))
            winner = s['maxima'][0]
            assert s['leader_id'] == winner['bidder_id']
            assert old_price <= s['current_minor'] <= winner['amount_minor']
            assert len({m['bidder_id'] for m in s['maxima']}) == len(s['maxima'])
            assert all(item['amount_minor'] <= winner['amount_minor'] for item in s['bids'])
