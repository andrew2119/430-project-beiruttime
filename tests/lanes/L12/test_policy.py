from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from uuid import uuid4
import pytest
from bt_runtime.modules import discover
from conftest import BUYER, OTHER, SELLER, headers


def policy_module():
    root=Path('/app/modules')
    if not root.exists(): root=Path('services/auction/modules')
    return next(module for module in discover(root) if module.id=='L12.extension-policy')


@pytest.mark.parametrize('remaining,extended',[(120.001,False),(120,True),(.001,True)])
def test_exact_accepted_bid_boundary(remaining,extended):
    hook=policy_module().load('policy.py:extension')
    end=datetime(2026,11,5,tzinfo=timezone.utc)
    result=hook({'ends_at':end.isoformat(),'end_version':7,'extension_policy':'last-two-minutes.v1'},
        {'accepted_at':(end-timedelta(seconds=remaining)).isoformat(),'public_bid':True})
    assert result['end_version']==7+int(extended)
    assert result['extended']==extended
    assert datetime.fromisoformat(result['ends_at'])==end+timedelta(seconds=120 if extended else 0)


@pytest.mark.parametrize('remaining',[0,-.001])
def test_deadline_is_not_browser_time(remaining):
    hook=policy_module().load('policy.py:extension')
    end=datetime(2026,11,5,tzinfo=timezone.utc)
    with pytest.raises(ValueError):hook({'ends_at':end.isoformat(),'end_version':1,'extension_policy':'last-two-minutes.v1'},
        {'accepted_at':(end-timedelta(seconds=remaining)).isoformat(),'public_bid':True})


def test_none_policy_and_private_cap_only_leave_current_end_unchanged():
    hook=policy_module().load('policy.py:extension')
    end=datetime(2026,11,5,tzinfo=timezone.utc)
    state={'ends_at':end.isoformat(),'end_version':7,'extension_policy':'none.v1'}
    bid={'accepted_at':(end-timedelta(seconds=1)).isoformat(),'public_bid':True}
    result=hook(state,bid)
    assert not result['extended'] and result['end_version']==7 and datetime.fromisoformat(result['ends_at'])==end
    state['extension_policy']='last-two-minutes.v1'
    assert hook(state,{**bid,'public_bid':False})=={'ends_at':end.isoformat(),'end_version':7,'extended':False}


def test_reserve_uses_price_not_private_cap():
    reserve=policy_module().load('policy.py:reserve_met')
    assert not reserve(current_minor=100, reserve_minor=110,accepted_sequence=1)
    assert not reserve(current_minor=110, reserve_minor=110,accepted_sequence=0)
    assert reserve(current_minor=110,reserve_minor=110,accepted_sequence=1)


async def test_current_owner_revision_and_public_privacy(api):
    client,app,fixture,id=api
    path=f'/v1/auctions/{id}/policy'
    public=await client.get(path)
    assert public.status_code==200
    assert public.json()['end_version']==1
    assert 'reserve_minor' not in public.text and str(SELLER) not in public.text
    command={'extension_policy':'none.v1','buy_now_minor':500000}
    assert (await client.patch(path,json=command,headers=headers(OTHER,revision=2))).status_code==403
    assert (await client.patch(path,json=command,headers=headers(SELLER,revision=1))).status_code==409
    first=await client.patch(path,json=command,headers=headers(SELLER,'configure',2))
    assert first.status_code==200,first.text
    same=await client.patch(path,json=command,headers=headers(SELLER,'configure',2))
    assert same.json()==first.json()
    conflict=await client.patch(path,json={**command,'buy_now_minor':510000},headers=headers(SELLER,'configure',2))
    assert conflict.status_code==409 and conflict.json()['error']['code']=='idempotency_conflict'
    assert (await client.patch(path,json={**command,'buy_now_minor':400000},headers=headers(SELLER,revision=3))).status_code==422
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='auction.policy-updated.v1'")==2


async def test_missing_kernel_holds_new_features_without_breaking_v1(api,monkeypatch):
    import sys
    client,app,fixture,id=api
    monkeypatch.setitem(sys.modules,'service_app.kernel',None)
    result=await client.get(f'/v1/auctions/{id}/policy')
    assert result.status_code==503 and result.json()['error']['code']=='kernel_unavailable'
    assert (await client.get(f'/v1/auctions/{id}')).status_code==200
    assert (await client.get('/health/live')).status_code==200


async def test_policy_freezes_after_actual_accepted_bid(api):
    client,app,fixture,id=api
    bid=await client.post(f'/v1/auctions/{id}/bids',headers=headers(),json={'amount_minor':400000,'expected_revision':2,'fee_quote_id':str(uuid4())})
    assert bid.status_code==200 and bid.json()['status']=='succeeded',bid.text
    result=await client.patch(f'/v1/auctions/{id}/policy',headers=headers(SELLER,revision=3),json={'extension_policy':'none.v1','buy_now_minor':None})
    assert result.status_code==409 and result.json()['error']['code']=='rules_frozen'
