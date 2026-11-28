import importlib
from copy import deepcopy
import pytest

MAYA = '00000000-0000-4000-8000-000000000001'
RAMI = '00000000-0000-4000-8000-000000000002'


@pytest.mark.parametrize('runtime', ['auction'], indirect=True)
@pytest.mark.parametrize('amount,leader,price', [(420000, MAYA, 430000), (445000, RAMI, 445000), (450000, RAMI, 450000)])
def test_full_step_frozen_examples_do_not_mutate_private_input(runtime, amount, leader, price):
    calculate = importlib.import_module('service_app.proxy_v2').calculate
    state = {'opening_minor': 400000, 'current_minor': 400000, 'leader_id': MAYA, 'sequence': 1,
             'increment_bands': [{'from_minor': 0, 'step_minor': 10000}],
             'maxima': [{'bidder_id': MAYA, 'amount_minor': 450000, 'sequence': 1, 'active': True}]}
    original = deepcopy(state)
    command = {'kind': 'manual', 'bidder_id': RAMI, 'amount_minor': amount, 'sequence': 2}
    result = calculate(state, command)
    assert state == original
    assert result['leader_id'] == leader and result['current_minor'] == price
    assert all(set(bid) == {'bidder_id', 'amount_minor', 'automatic'} for bid in result['bids'])
    assert all(not m['active'] or m['bidder_id'] == leader for m in result['maxima'])
    assert len({bid['amount_minor'] for bid in result['bids']}) == len(result['bids'])
    with pytest.raises(ValueError):
        calculate(state, {**command, 'sequence': 1})
    with pytest.raises(ValueError):
        calculate(state, {**command, 'amount_minor': True})
