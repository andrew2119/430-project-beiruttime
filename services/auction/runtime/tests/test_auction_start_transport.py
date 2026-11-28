import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from bt_contracts_core.errors import PublicError
from service_app.dependencies import Dependencies


def uid(number):
    return str(UUID(int=number))


@pytest.mark.parametrize('status', ['succeeded','denied','wrong_source','wrong_revision','missing_receipt','lost'])
def test_start_orders_replays_only_the_exact_admitted_command(status):
    intent=dict(auction_id=uid(1),watch_id=uid(2),listing_id=uid(3),seller_id=uid(4),listing_revision=2,watch_revision=7)
    watch=dict(watch_id=uid(2),listing_id=uid(3),seller_id=uid(4),listing_revision=2,organization_id=None,
               source_id=uid(5) if status=='wrong_source' else uid(1),source_kind='auction_open',revision=9 if status=='wrong_revision' else 8,
               auction_committed=False,status='fenced',sale_mode='auction')
    receipt=dict(id=uid(6),status='denied' if status=='denied' else 'succeeded',watch=watch)
    if status=='missing_receipt':
        del receipt['id']
    deps=Dependencies(clients={'orders':object()})
    deps.service_headers=lambda _,audience:{'Authorization':'Bearer auction-for-'+audience}
    deps.json=AsyncMock(return_value=receipt)
    if status=='lost':
        deps.json.side_effect=PublicError('dependency_unavailable','Orders unavailable.',status=503)
    request=SimpleNamespace()
    for _ in range(2):
        if status in ('succeeded','denied'):
            assert asyncio.run(deps.start_commitment(request,intent,None))==receipt
        else:
            with pytest.raises(PublicError,match='sale_mode_pending'):
                asyncio.run(deps.start_commitment(request,intent,None))
    assert deps.json.await_args_list[0]==deps.json.await_args_list[1]
    args,kwargs=deps.json.await_args
    assert args==('orders','POST','/internal/v2/commitments',request)
    key='auction-open:'+uid(1)
    assert kwargs=={'headers':{'Authorization':'Bearer auction-for-orders','Idempotency-Key':key},
                    'json':dict(operation_key=key,watch_id=uid(2),listing_id=uid(3),listing_revision=2,
                                expected_revision=7,source_id=uid(1),kind='auction_open',reason='Open ordinary auction')}


@pytest.mark.parametrize('state', ['released','superseded','wrong_scope'])
def test_start_compensation_requires_original_orders_receipt_binding(state):
    intent=dict(auction_id=uid(1),watch_id=uid(2),listing_id=uid(3),listing_revision=2,watch_revision=7,
                open_operation_id=uid(4),release_reason='listing_changed')
    deps=Dependencies(clients={'orders':object()})
    deps.service_headers=lambda _,audience:{'Authorization':'Bearer auction-for-'+audience}
    open_key='auction-open:'+uid(1)
    release_key='auction-open-release:'+uid(1)
    scope=dict(operation_key=release_key,open_operation_id=uid(4),auction_id=uid(1),listing_id=uid(3),watch_id=uid(2),
               listing_revision=2,expected_revision=8)
    result=dict(scope,id=uid(5),state='released' if state=='wrong_scope' else state)
    if state=='wrong_scope':
        result['open_operation_id']=uid(9)
    deps.json=AsyncMock(return_value=result)
    request=SimpleNamespace()
    if state=='wrong_scope':
        with pytest.raises(PublicError,match='sale_mode_pending'):
            asyncio.run(deps.release_start_commitment(request,intent,open_key))
    else:
        asyncio.run(deps.release_start_commitment(request,intent,open_key))
    deps.json.assert_awaited_once_with('orders','POST','/internal/v2/auction-open-releases',request,
        headers={'Authorization':'Bearer auction-for-orders','Idempotency-Key':release_key},
        json=dict(scope,open_operation_key=open_key,reason='listing_changed'))


@pytest.mark.parametrize('state', ['abandoned','released','superseded','wrong_scope','unknown'])
def test_expiry_requires_an_exact_atomic_orders_outcome(state):
    intent=dict(auction_id=uid(1),watch_id=uid(2),listing_id=uid(3),listing_revision=2,watch_revision=7)
    deps=Dependencies(clients={'orders':object()})
    deps.service_headers=lambda _,audience:{'Authorization':'Bearer auction-for-'+audience}
    key='auction-open-expire:'+uid(1)
    receipt=dict(id=uid(5),operation_key=key,auction_id=uid(1),watch_id=uid(2),listing_id=uid(3),
                 listing_revision=2,expected_revision=7,state='released' if state=='wrong_scope' else state)
    if state=='wrong_scope':
        receipt['watch_id']=uid(9)
    deps.json=AsyncMock(return_value=receipt)
    request=SimpleNamespace()
    if state in ('abandoned','released','superseded'):
        asyncio.run(deps.expire_start_commitment(request,intent))
    else:
        with pytest.raises(PublicError,match='sale_mode_pending'):
            asyncio.run(deps.expire_start_commitment(request,intent))
    deps.json.assert_awaited_once_with('orders','POST','/internal/v2/auction-open-expirations',request,
        headers={'Authorization':'Bearer auction-for-orders','Idempotency-Key':key},
        json={'operation_key':key,'original':deps.opening_command(intent)})
