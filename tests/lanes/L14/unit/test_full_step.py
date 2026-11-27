import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from uuid import UUID
import pytest
from conftest import load, ROOT
from bt_contracts_core.errors import PublicError
from bt_contracts.auction.core.models import BidCommand, AuctionRules, MAX_MINOR

validation = load('full_step_validation', 'services/auction/runtime/service_app/proxy_validation.py')
kernel = load('fixed_kernel', 'services/auction/runtime/service_app/kernel.py')
MAYA, RAMI, THIRD = (str(UUID(int=i)) for i in (1, 2, 3))


def state(price=430000):
    return {'opening_minor': 400000, 'current_minor': price, 'leader_id': MAYA, 'sequence': 3,
            'increment_bands': [{'from_minor': 0, 'step_minor': 10000}],
            'maxima': [{'bidder_id': MAYA, 'amount_minor': 450000, 'sequence': 1, 'active': True}]}


def calculate(s, amount, kind='manual', bidder=RAMI):
    c = {'bidder_id': bidder, 'kind': kind, 'amount_minor': amount, 'sequence': s['sequence'] + 1}
    result = validation.expected_result(s, c)
    validation.validate_result(s, c, result)
    return c, result


@pytest.mark.parametrize('amount', [445000, 450000])
def test_insufficient_incumbent_cannot_tie_or_answer_partial_step(amount):
    _, result = calculate(state(), amount)
    assert result['leader_id'] == RAMI
    assert len(result['bids']) == 1 and result['current_minor'] == amount
    assert next(m for m in result['maxima'] if m['bidder_id'] == MAYA)['active'] is False


def test_full_step_response_later_equal_maximum_and_no_inactive_return():
    s = state(400000)
    _, result = calculate(s, 420000)
    assert result['leader_id'] == MAYA and result['current_minor'] == 430000
    c, result = calculate(state(), 450000, 'maximum')
    assert result['leader_id'] == RAMI and result['current_minor'] == 450000
    s.update(result, sequence=c['sequence'])
    _, later = calculate(s, 460000, bidder=THIRD)
    assert later['leader_id'] == THIRD
    assert not next(m for m in later['maxima'] if m['bidder_id'] == MAYA)['active']


def test_displaced_higher_ceiling_never_returns_on_leader_raise():
    s = state()
    command, displaced = calculate(s, 445000)
    s.update(displaced, sequence=command['sequence'])
    _, raised = calculate(s, 449000, 'maximum', RAMI)
    assert raised['leader_id'] == RAMI and raised['current_minor'] == 445000 and raised['bids'] == []
    assert next(m for m in raised['maxima'] if m['bidder_id'] == MAYA)['active'] is False


def test_opening_ceiling_raise_and_challenger_band():
    s = {'opening_minor': 400000, 'current_minor': 400000, 'leader_id': None, 'sequence': 0,
         'increment_bands': [{'from_minor': 0, 'step_minor': 10000}], 'maxima': []}
    _, result = calculate(s, 450000, 'maximum', MAYA)
    assert result['current_minor'] == 400000
    s.update(result, sequence=1)
    _, raised = calculate(s, 470000, 'maximum', MAYA)
    assert raised['bids'] == [] and raised['current_minor'] == 400000
    s['increment_bands'].append({'from_minor': 420000, 'step_minor': 20000})
    _, result = calculate(s, 420000)
    assert result['current_minor'] == 440000


@pytest.mark.parametrize('change', ['tie', 'private', 'inactive', 'unbounded', 'boolean', 'extra', 'duplicate'])
def test_validator_rejects_malformed_and_leaking_results(change):
    s = state(400000)
    c, result = calculate(s, 420000)
    bad = deepcopy(result)
    if change == 'tie':
        bad['bids'][-1]['amount_minor'] = 420000
    elif change == 'private':
        bad['bids'][-1]['maximum_minor'] = 450000
    elif change == 'inactive':
        bad['maxima'][0]['active'] = False
    elif change == 'unbounded':
        bad['maxima'][0]['amount_minor'] = MAX_MINOR + 1
    elif change == 'boolean':
        bad['maxima'][0]['active'] = 1
    elif change == 'extra':
        bad['surprise'] = True
    else:
        bad['maxima'].append(bad['maxima'][0])
    with pytest.raises(PublicError):
        validation.validate_result(s, c, bad)


def test_fixed_end_never_invokes_extension_hook():
    end = datetime.now(timezone.utc) + timedelta(hours=1)
    def forbidden(*args):
        raise AssertionError('Timing hook must not run')
    assert kernel.extension({'auction.policy.accepted-bid.v1': forbidden},
        {'scheduled_ends_at': end, 'end_version': 1}, {'bids': [{}]}, end - timedelta(seconds=1)) == (end, 1)


def test_new_auction_purchase_denied_before_touching_transaction():
    with pytest.raises(PublicError) as exc:
        asyncio.run(kernel.transition(None, UUID(int=1), expected_revision=1, expected_end_version=1,
                                      from_mode='bidding', to_mode='prebid_pending'))
    assert exc.value.code == 'auction_purchase_disabled'


def test_first_bid_does_not_permit_close_before_scheduled_end(monkeypatch):
    now = datetime.now(timezone.utc)
    async def lock(*args):
        return {'revision': 1, 'end_version': 1, 'mode': 'bidding', 'accepted_sequence': 1,
                'first_bid_confirmed': True, 'ends_at': now + timedelta(hours=1)}
    async def clock(*args):
        return now
    monkeypatch.setattr(kernel, 'lock_lot', lock)
    monkeypatch.setattr(kernel, 'server_now', clock)
    with pytest.raises(PublicError) as exc:
        asyncio.run(kernel.transition(None, UUID(int=1), expected_revision=1, expected_end_version=1,
                                      from_mode='bidding', to_mode='closed_winner'))
    assert exc.value.code == 'auction_not_ended'


def test_active_money_boundaries_and_additive_migration():
    with pytest.raises(ValueError):
        BidCommand(amount_minor=1.5, fee_quote_id=UUID(int=4), expected_revision=1)
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        AuctionRules(currency='LBP', opening_minor=400000, increment_bands=[{'from_minor': 0, 'step_minor': 10000}],
                     starts_at=now, ends_at=now + timedelta(hours=1))
    migration = (ROOT / 'services/auction/modules/rules/kernel-v2/migrations/L14_0009_full_step.sql').read_text()
    assert 'ACCESS EXCLUSIVE' in migration and 'm.bidder_id=l.leader_id' in migration
    assert "DEFAULT 'ordinary.v1'" in migration and 'auction_fixed_end' in migration
