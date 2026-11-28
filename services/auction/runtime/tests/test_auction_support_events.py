import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Response
from jsonschema import Draft202012Validator, FormatChecker

from bt_contracts_core.errors import PublicError
from bt_runtime.modules import discover


@pytest.fixture
def loader():
    import sys
    root = next((parent / 'services/auction/modules' for parent in Path(__file__).resolve().parents
                 if (parent / 'services/auction/modules').is_dir()), Path('/app/modules'))
    module = next(item for item in discover(root) if item.id == 'L13.closing')
    return lambda target: sys.modules[module.load(target).__module__]


@pytest.fixture
def validate_facts():
    schema = next((parent / 'packages/contracts-auction/results/buyer-support.v1.schema.json'
                   for parent in Path(__file__).resolve().parents
                   if (parent / 'packages/contracts-auction/results/buyer-support.v1.schema.json').is_file()),
                  Path('/contracts/auction/buyer-support.v1.schema.json'))
    return Draft202012Validator(json.loads(schema.read_text()), format_checker=FormatChecker()).validate


@pytest.fixture
def publisher(loader):
    return loader('support_events.py:retain_support')


@pytest.mark.parametrize('state,finance', [('allocation_pending', None), ('allocation_denied', None), ('closed', 9)])
def test_support_event_seals_actual_result_and_original_hold(publisher, validate_facts, state, finance):
    auction, listing, watch, buyer, order = map(UUID, [f'00000000-0000-0000-0000-{n:012}' for n in range(1, 6)])
    created = datetime(2030, 1, 1, 12, tzinfo=timezone(timedelta(hours=2)))
    row = dict(auction_id=auction, order_id=order if finance else None, winner_id=buyer, state=state,
               created_at=created, result_revision=1 if state=='allocation_pending' else 2)
    tx = SimpleNamespace(execute=AsyncMock())
    if finance:
        with pytest.raises(ValueError, match='Unbound'):
            asyncio.run(publisher.retain_support(tx, row, listing_id=listing, watch_id=watch))
        tx.execute.assert_not_called()
    asyncio.run(publisher.retain_support(tx, row, listing_id=listing, watch_id=watch, financial_revision=finance))
    sql, key, stored_auction, revision, stored = tx.execute.await_args.args
    assert 'INSERT INTO l13_auction_support_outbox' in sql
    assert key.version==4 and stored_auction==auction and revision==row['result_revision']
    validate_facts(json.loads(stored))
    assert json.loads(stored)==dict(schema_version=1, auction_id=str(auction), listing_id=str(listing), watch_id=str(watch),
        buyer_id=str(buyer), order_id=str(order) if finance else None, result_revision=revision, financial_revision=finance,
        held_since='2030-01-01T10:00:00Z', reason=None if finance else state)


@pytest.mark.parametrize('status,final', [('succeeded','closed'), ('denied','allocation_denied'), ('unbound',None)])
def test_allocation_transition_retains_support_inside_the_canonical_write(loader, monkeypatch, validate_facts, status, final):
    reconcile=loader('reconcile.py:reconcile')
    auction,watch,listing,buyer,order,quote=(UUID(int=index) for index in range(1,7))
    payload=dict(watch_id=str(watch),listing_id=str(listing),quote_id=str(quote),currency='USD',total_minor=500000)
    now=datetime(2030,1,1,tzinfo=timezone.utc)
    held=dict(auction_id=auction,winner_id=buyer,order_id=None,allocation_payload=json.dumps(payload),
              end_version=1,close_version=1,closing_minor=500000,state='allocation_pending',created_at=now,result_revision=1)
    entered=False
    statements=[]

    class Database:
        async def fetchrow(self, sql, *args):
            assert entered
            if 'SET lease=$2' in sql:
                return held
            assert 'state=$3' in sql and args[0]==auction and args[2]==final
            statements.append('allocation')
            return dict(held,state=final,order_id=args[3],result_revision=2)

        async def execute(self, sql, *args):
            statements.append('support' if 'INSERT INTO l13_auction_support_outbox' in sql else 'retry')
            assert entered==('INSERT INTO l13_auction_support_outbox' in sql)
            if entered:
                facts=json.loads(args[-1])
                validate_facts(facts)
                assert (facts['result_revision'],facts['held_since'])==(2,'2030-01-01T00:00:00Z')
                assert facts['financial_revision']==(3 if final=='closed' else None)

    @asynccontextmanager
    async def atomic(pool):
        nonlocal entered
        assert not entered
        entered=True
        try:
            yield Database()
        finally:
            entered=False

    @asynccontextmanager
    async def acquire():
        yield Database()

    async def peer(name, method, path, **options):
        assert not entered and (name,method,path)==('orders','POST','/internal/v2/allocations')
        assert options==dict(headers={'Idempotency-Key':'close:'+str(auction)},json=payload)
        result={'status':'denied'} if status=='denied' else {
            'status':'succeeded','order':dict(payload,id=str(order),buyer_id=str(buyer))}
        if status=='succeeded':
            result['auction_support_financial_revision']=3
        return result

    async def enqueue(tx, event, recipients):
        assert entered and event.type=='auction.closed.v1' and recipients==['communications-auction-results']
        statements.append('public-close')

    monkeypatch.setattr(reconcile,'unit_of_work',atomic)
    monkeypatch.setattr(reconcile,'enqueue',enqueue)
    app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire)))
    asyncio.run(reconcile.reconcile(app,SimpleNamespace(json=peer),auction))
    assert statements==(['retry'] if final is None else ['allocation','support']+(['public-close'] if final=='closed' else []))


def test_delivery_retries_exact_event_and_waits_for_boolean_ack(publisher):
    event_id=UUID(int=1)
    deliveries=[]
    facts={'auction_id':str(UUID(int=2)),'result_revision':1}
    async def claim(sql, token):
        assert 'older.result_revision<o.result_revision AND older.delivered_at IS NULL' in sql
        assert 'FOR UPDATE OF o SKIP LOCKED' in sql
        return [{'event_id':event_id,'facts':json.dumps(facts)}]
    async def post(name, method, path, *,json):
        assert (name,method,path)==('communications','POST','/internal/v1/support/auction-results/events')
        deliveries.append(json)
        return {'accepted':1 if len(deliveries)==1 else True}
    pool=SimpleNamespace(fetch=AsyncMock(side_effect=claim),execute=AsyncMock())
    source=SimpleNamespace(json=post)
    asyncio.run(publisher.deliver_support(pool,source))
    asyncio.run(publisher.deliver_support(pool,source))
    assert deliveries==[{'event_id':str(event_id),'facts':facts}]*2
    first,second=[call.args for call in pool.execute.await_args_list]
    assert 'SET available_at' in first[0] and 'SET delivered_at' in second[0]
    for args,claim_call in zip((first,second),pool.fetch.await_args_list,strict=True):
        assert args[1:]==(event_id,claim_call.args[1]) and 'lease_token=$2' in args[0]


def test_orders_anchor_requires_acknowledged_exact_allocation(publisher, monkeypatch):
    auction, order = UUID(int=1), UUID(int=2)
    fact = dict(auction_id=str(auction),listing_id=str(UUID(int=3)),watch_id=str(UUID(int=4)),buyer_id=str(UUID(int=5)),
                order_id=str(order),held_since='2030-01-01T10:00:00Z',result_revision=2,financial_revision=9,reason=None)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(fetchrow=AsyncMock(
        side_effect=[None,{'facts':json.dumps(fact)}])))))
    def authenticate(current, callers):
        assert current is request and callers=={'orders'}
    monkeypatch.setattr(publisher,'service',authenticate)
    with pytest.raises(PublicError,match='auction_support_binding_unavailable'):
        asyncio.run(publisher.delivery_binding(auction,order,request,Response()))
    response=Response()
    answer=asyncio.run(publisher.delivery_binding(auction,order,request,response))
    assert answer=={key:value for key,value in fact.items() if key not in ('financial_revision','reason')}
    sql,*args=request.app.state.pool.fetchrow.await_args.args
    assert 'o.delivered_at IS NOT NULL' in sql and args==[auction,order,str(order)]
    assert response.headers['Cache-Control']=='no-store'
