from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import ValidationError
from bt_contracts.auction.policy.models import ConfigurePolicy
from bt_runtime.modules import discover


def policy_module():
    return next(module for module in discover(Path('services/auction/modules')) if module.id == 'L12.extension-policy')


@pytest.mark.parametrize('remaining', [120, 90, .001])
@pytest.mark.parametrize('kind', ['manual', 'proxy', 'ceiling_only'])
@pytest.mark.parametrize('stored_policy', ['none.v1', 'last-two-minutes.v1'])
def test_accepted_bid_keeps_scheduled_end(remaining, kind, stored_policy):
    hook = policy_module().load('policy.py:extension')
    end = datetime(2026, 11, 16, tzinfo=timezone.utc)
    result = hook({'ends_at': end.isoformat(), 'end_version': 7, 'extension_policy': stored_policy},
        {'accepted_at': (end-timedelta(seconds=remaining)).isoformat(), 'public_bid': kind != 'ceiling_only'})
    assert result['end_version'] == 7 and result['extended'] is False
    assert datetime.fromisoformat(result['ends_at']) == end


@pytest.mark.parametrize('remaining', [0, -.001])
@pytest.mark.parametrize('public_bid', [True, False])
def test_deadline_is_not_browser_time(remaining, public_bid):
    end = datetime(2026, 11, 16, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        policy_module().load('policy.py:extension')({'ends_at': end.isoformat(), 'end_version': 1},
            {'accepted_at': (end-timedelta(seconds=remaining)).isoformat(), 'public_bid': public_bid})


@pytest.mark.parametrize('command', [{'extension_policy': 'last-two-minutes.v1'}, {'extension_policy': 'none.v1'}, {'buy_now_minor': 500000}])
def test_configuration_rejects_removed_controls(command):
    with pytest.raises(ValidationError):
        ConfigurePolicy.model_validate(command)


def test_reserve_uses_final_public_price_not_private_cap():
    reserve = policy_module().load('policy.py:reserve_met')
    assert not reserve(current_minor=430000, reserve_minor=450000, accepted_sequence=2)
    assert not reserve(current_minor=450000, reserve_minor=450000, accepted_sequence=0)
    assert reserve(current_minor=450000, reserve_minor=450000, accepted_sequence=1)
    assert not reserve(current_minor=0, reserve_minor=None, accepted_sequence=0)


@pytest.mark.asyncio
async def test_public_snapshot_has_no_private_reserve_comparison(monkeypatch):
    from types import SimpleNamespace
    module = policy_module()
    routes = module.load('routes.py:snapshot')
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    async def server_now(tx): return now
    monkeypatch.setitem(routes.__globals__, 'get_kernel', lambda: SimpleNamespace(server_now=server_now))
    lot = {'id': uuid4(), 'revision': 2, 'end_version': 1, 'starts_at': now-timedelta(hours=1),
        'ends_at': now, 'accepted_sequence': 0, 'current_minor': 0, 'reserve_minor': 450000, 'mode': 'prebid_pending'}
    public = await routes(None, lot)
    assert public['schedule_state'] == 'ended_legacy_review'
    assert not {'reserve_met', 'reserve_minor', 'buy_now_minor', 'extension_policy'} & public.keys()
    private = await routes(None, lot, private=True)
    assert private['reserve_met'] is False and private['cancellation_eligible'] is False
    lot.update(mode='bidding', ends_at=now+timedelta(seconds=1))
    assert (await routes(None, lot, private=True))['cancellation_eligible'] is True
    lot['accepted_sequence'] = 1
    assert (await routes(None, lot, private=True))['cancellation_eligible'] is False
