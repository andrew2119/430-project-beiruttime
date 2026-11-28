from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from uuid import UUID
import pytest
from bt_contracts.auction.proxy.notices import outbid_recipients
from bt_contracts_core.errors import PublicError
from bt_runtime.modules import discover

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'services').is_dir())
spec = importlib.util.spec_from_file_location('proxy_v2', ROOT / 'services/auction/modules/proxy/proxy.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
calculate = module.calculate_v2


def initial():
    return dict(opening_minor=400000, current_minor=400000, leader_id=None,
                sequence=0, increment_bands=[dict(from_minor=0, step_minor=10000)], maxima=[])


def bid(state, buyer, amount, kind='maximum'):
    sequence = state['sequence'] + 1
    result = calculate(state, dict(kind=kind, bidder_id=buyer, amount_minor=amount, sequence=sequence))
    return dict(state, **result, sequence=sequence)


@pytest.mark.parametrize(('challenge', 'price', 'leader'), [
    (440000, 450000, 'maya'),
    (440001, 440001, 'rami'),
    (445000, 445000, 'rami'),
    (450000, 450000, 'rami'),
])
def test_full_step_response_boundary(challenge, price, leader):
    state = bid(bid(initial(), 'maya', 450000), 'rami', 420000, 'manual')
    assert state['current_minor'] == 430000
    result = bid(state, 'rami', challenge, 'manual')
    assert result['leader_id'] == leader
    assert result['current_minor'] == price
    expected = [dict(bidder_id='rami', amount_minor=challenge, automatic=False)]
    if leader == 'maya':
        expected.append(dict(bidder_id='maya', amount_minor=price, automatic=True))
    assert result['bids'] == expected
    assert result['maxima'] == [
        dict(bidder_id='maya', amount_minor=450000, sequence=1, active=leader == 'maya'),
    ]


@pytest.mark.parametrize('challenge', [440001, 445000, 450000])
def test_canonical_validator_accepts_full_step_without_creating_manual_ceiling(challenge, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'services/auction/runtime'))
    from service_app.engine import AuctionEngine

    maya, rami = str(UUID(int=1)), str(UUID(int=2))
    state = bid(bid(initial(), maya, 450000), rami, 420000, 'manual')
    # The earlier challenge generated both a manual bid and an automatic bid.
    state['sequence'] = 3
    command = dict(kind='manual', bidder_id=rami, amount_minor=challenge, sequence=4)
    result = calculate(state, command)
    assert result['leader_id'] == rami
    assert result['maxima'] == [
        dict(bidder_id=maya, amount_minor=450000, sequence=1, active=False),
    ]

    AuctionEngine.validate_result(state, command, result)
    invented = dict(bidder_id=rami, amount_minor=challenge, sequence=4, active=True)
    with pytest.raises(PublicError) as rejected:
        AuctionEngine.validate_result(state, command, dict(result, maxima=[*result['maxima'], invented]))
    assert rejected.value.code == 'proxy_unavailable'


def test_later_equal_maximum_wins_without_equal_public_row():
    result = bid(bid(initial(), 'leila', 450000), 'sami', 450000)
    assert result['leader_id'] == 'sami'
    assert result['bids'] == [dict(bidder_id='sami', amount_minor=450000, automatic=True)]


def test_inactive_ceiling_never_returns_by_sorting_or_manual_bid():
    state = bid(bid(initial(), 'maya', 450000), 'rami', 445000, 'manual')
    # A higher inactive ceiling is never consulted as a competitor.
    state['maxima'].append(dict(bidder_id='old', amount_minor=900000, sequence=3, active=False))
    state['sequence'] = 3
    result = bid(state, 'third', 460000, 'manual')
    assert result['leader_id'] == 'third'
    assert len(result['bids']) == 1
    result = bid(result, 'old', 480000, 'manual')
    assert not next(m for m in result['maxima'] if m['bidder_id'] == 'old')['active']
    result = bid(result, 'fourth', 500000, 'manual')
    assert result['leader_id'] == 'fourth'
    result = bid(result, 'old', 910000)
    assert next(m for m in result['maxima'] if m['bidder_id'] == 'old')['active']


def test_ceiling_raise_is_private_and_inputs_unchanged():
    state = bid(initial(), 'maya', 450000)
    before = deepcopy(state)
    result = bid(state, 'maya', 460000)
    assert state == before
    assert result['current_minor'] == 400000
    assert result['bids'] == []


@pytest.mark.parametrize('challenge,price', [(419999,429999),(420000,440000),(420001,440001)])
def test_challenger_band_before_equal_after(challenge, price):
    state = initial()
    state['increment_bands'].append(dict(from_minor=420000, step_minor=20000))
    result = bid(bid(state, 'maya', 500000), 'rami', challenge, 'manual')
    assert result['current_minor'] == price
    assert all(set(row) == {'bidder_id','amount_minor','automatic'} for row in result['bids'])


@pytest.mark.parametrize('amount', [True, 1.2, float('inf'), '450000', -1, 0, module.MAX_MINOR+1])
def test_exact_money_only(amount):
    with pytest.raises(ValueError):
        bid(initial(), 'maya', amount)


def test_raise_only_and_minimum():
    state = bid(initial(), 'maya', 450000)
    for owner, amount in [('maya',450000), ('maya',440000), ('rami',409999)]:
        with pytest.raises(ValueError):
            bid(state, owner, amount)


def test_fixture_and_invalid_active_owner():
    case = json.loads((ROOT / 'packages/contracts-auction/proxy/fixtures/competition.v2.json').read_text())
    assert calculate(case['state'], case['command']) == case['result']
    case['state']['maxima'][1]['active'] = True
    with pytest.raises(ValueError):
        calculate(case['state'], case['command'])


@pytest.mark.parametrize(
    ('bidder', 'previous_leader', 'leader', 'expected'),
    [
        ('maya', None, 'maya', []),
        ('maya', 'maya', 'maya', []),
        ('rami', 'maya', 'maya', ['rami']),
        ('rami', 'maya', 'rami', ['maya']),
        ('maya', 'maya', 'rami', ['maya']),
    ],
)
def test_outbid_recipients_from_accepted_event(bidder, previous_leader, leader, expected):
    assert outbid_recipients(
        bidder_id=bidder, previous_leader_id=previous_leader, leader_id=leader,
    ) == expected


@pytest.mark.parametrize('challenge', [445000, 450000])
def test_registered_v2_hook_calculates_full_step_displacement(challenge):
    proxy = next(m for m in discover(ROOT / 'services/auction/modules') if m.id == 'L06.proxy')
    current = proxy.load(proxy.hooks['auction.proxy.v2'])
    state = bid(bid(initial(), 'maya', 450000), 'rami', 420000, 'manual')
    before = deepcopy(state)
    command = dict(kind='manual', bidder_id='rami', amount_minor=challenge, sequence=state['sequence'] + 1)
    result = current(state, command)
    assert result['leader_id'] == 'rami'
    assert result['current_minor'] == challenge
    assert result['bids'] == [dict(bidder_id='rami', amount_minor=challenge, automatic=False)]
    assert dict(bidder_id='maya', amount_minor=450000, sequence=1, active=False) in result['maxima']
    assert state == before


def test_registered_legacy_hook_preserves_ordinary_bids_without_competition():
    proxy = next(m for m in discover(ROOT / 'services/auction/modules') if m.id == 'L06.proxy')
    legacy = proxy.load(proxy.hooks['auction.proxy.v1'])
    state = initial()
    for sequence, buyer, amount in [(1, 'maya', 400000), (2, 'rami', 410000), (3, 'maya', 420000)]:
        command = dict(kind='manual', bidder_id=buyer, amount_minor=amount, sequence=sequence)
        result = legacy(state, command)
        assert result['leader_id'] == buyer
        assert result['bids'] == [dict(bidder_id=buyer, amount_minor=amount, automatic=False)]
        state = state | result | {'sequence': sequence}


def test_registered_current_hook_accepts_opening_maximum():
    proxy = next(m for m in discover(ROOT / 'services/auction/modules') if m.id == 'L06.proxy')
    calculate = proxy.load(proxy.hooks['auction.proxy.v2'])
    command = dict(kind='maximum', bidder_id='maya', amount_minor=450000, sequence=1)
    result = calculate(initial(), command)
    assert result['leader_id'] == 'maya'
    assert result['current_minor'] == 400000
    assert result['bids'] == [dict(bidder_id='maya', amount_minor=400000, automatic=True)]
    assert result['maxima'][0]['amount_minor'] == 450000


@pytest.mark.parametrize('challenge', [420000, 445000, 450000])
def test_registered_validator_preserves_public_rows_and_private_ceiling(challenge):
    proxy = next(m for m in discover(ROOT / 'services/auction/modules') if m.id == 'L06.proxy')
    transition = proxy.load(proxy.hooks['auction.proxy.v2'])
    validate = proxy.load(proxy.hooks['auction.proxy.validate.v2'])
    state = bid(initial(), 'maya', 450000)
    if challenge != 420000:
        state = dict(bid(state, 'rami', 420000, 'manual'), sequence=3)
    command = dict(kind='manual', bidder_id='rami', amount_minor=challenge,
                   sequence=state['sequence'] + 1)
    result = transition(state, command)
    validate(state, command, result)

    cap = result['maxima'][0]
    public = result['bids'][0]
    for altered in (
        dict(result, maxima=[]),
        dict(result, maxima=[dict(cap, active=not cap['active'])]),
        dict(result, maxima=[dict(cap, active=int(cap['active']))]),
        dict(result, bids=[dict(public, amount_minor=public['amount_minor'] + 1), *result['bids'][1:]]),
        dict(result, bids=[dict(public, private_maximum=cap['amount_minor']), *result['bids'][1:]]),
    ):
        with pytest.raises(ValueError, match='invalid_proxy_result'):
            validate(state, command, altered)


def test_canonical_registration_uses_the_d27_transition():
    proxy = next(m for m in discover(ROOT / 'services/auction/modules') if m.id == 'L06.proxy')
    assert proxy.hooks['auction.proxy.v2'] == 'proxy.py:calculate_v2'


def test_manual_leader_has_no_ceiling_until_setting_one():
    state = bid(initial(), 'maya', 400000, 'manual')
    assert state['maxima'] == []
    state = bid(state, 'rami', 420000, 'manual')
    assert state['maxima'] == []
    with pytest.raises(ValueError, match='below_current_bid'):
        bid(state, 'rami', 410000)
    result = bid(state, 'rami', 450000)
    assert result['bids'] == []
    assert result['maxima'] == [dict(bidder_id='rami', amount_minor=450000, sequence=3, active=True)]


def test_manual_bid_above_displaced_ceiling_preserves_private_amount_and_sequence():
    state = bid(bid(initial(), 'maya', 450000), 'rami', 445000, 'manual')
    result = bid(state, 'maya', 460000, 'manual')
    assert result['leader_id'] == 'maya'
    assert result['maxima'] == state['maxima']
    raised = bid(result, 'maya', 470000)
    assert raised['bids'] == []
    assert raised['maxima'][0]['active'] is True


@pytest.mark.parametrize(('challenge', 'expected_outbid'), [
    (440000, 'rami'),
    (445000, 'maya'),
    (450000, 'maya'),
])
def test_registered_v2_retains_ceiling_activity_and_outbid_facts(challenge, expected_outbid):
    proxy = next(m for m in discover(ROOT / 'services/auction/modules') if m.id == 'L06.proxy')
    hook = proxy.load(proxy.hooks['auction.proxy.v2'])
    before = dict(bid(bid(initial(), 'maya', 450000), 'rami', 420000, 'manual'), sequence=3)
    command = dict(kind='manual', bidder_id='rami', amount_minor=challenge,
                   sequence=before['sequence'] + 1)

    result = hook(before, command)
    assert outbid_recipients(
        bidder_id='rami', previous_leader_id=before['leader_id'], leader_id=result['leader_id'],
    ) == [expected_outbid]
    assert all(set(row) == {'bidder_id', 'amount_minor', 'automatic'} for row in result['bids'])

    persisted = json.loads(json.dumps({
        **before, **result, 'sequence': command['sequence'] + len(result['bids']) - 1,
    }))
    next_command = dict(kind='manual', bidder_id='third', amount_minor=460000,
                        sequence=persisted['sequence'] + 1)
    following = hook(persisted, next_command)
    assert following['leader_id'] == 'third'
    assert following['maxima'] == [
        dict(bidder_id='maya', amount_minor=450000, sequence=1, active=False),
    ]
