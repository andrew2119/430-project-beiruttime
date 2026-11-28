import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID
import pytest
from pydantic import ValidationError
from bt_contracts.pricing.counteroffers.current import Command, Offer, Economics, Authority, Facts, Result
from counteroffer_module.engine import decide
from counteroffer_module.service import Counteroffers

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
def uid(n):
    return UUID(int=n)

@pytest.fixture
def data():
    economics = Economics(quote_id=uid(8), quote_revision=1, policy_revision=1,
        currency='USD', price_minor=500000, buyer_fee_minor=15000,
        seller_commission_minor=25000, total_minor=515000, terms_revision=1)
    offer = Offer(id=uid(1), subject_id=uid(2), watch_id=uid(3), seller_id=uid(4),
        buyer_id=uid(5), organization_id=uid(6), revision=1, state='sent', economics=economics,
        sent_at=NOW-timedelta(hours=2), expires_at=NOW+timedelta(hours=46))
    authority = Authority(actor_id=uid(4), organization_id=uid(6), permitted=True,
        seller_approved=True, scope_revision=2)
    facts = Facts(watch_id=uid(3), subject_id=uid(2), source_revision=3,
        mode='fixed', available=True, blocked=False, quote_current=True, economics=economics)
    command = Command(operation_id=uid(7), subject_id=uid(2), watch_id=uid(3), actor_id=uid(4),
        organization_id=uid(6), expected_revision=1, source_revision=3, authority_revision=2, kind='propose', economics=economics)
    return command, offer, authority, facts

def run(data, **updates):
    c, o, a, f = data
    return decide(updates.get('command', c), updates.get('offer', o),
        updates.get('authority', a), updates.get('facts', f), updates.get('now', NOW))

def buyer(data, kind='accept'):
    c,o,a,f=data
    return (c.model_copy(update={'kind':kind,'actor_id':o.buyer_id,'reviewed_revision':1}),o,
        a.model_copy(update={'actor_id':o.buyer_id}),f)

def test_supersedes_fresh_lifetime(data):
    result, new = run(data)
    assert result.state == 'succeeded' and result.code == 'superseded'
    assert new.predecessor_id == data[1].id and new.id != data[1].id
    assert new.revision == 2 and new.sent_at == NOW
    assert new.expires_at == NOW + timedelta(hours=48)
    assert new.economics.total_minor == 515000
    assert data[1].revision == 1
    assert run(data)[1] == new

def test_stale_acceptance_after_counter(data):
    _, new = run(data)
    result,_=run(buyer(data), offer=new)
    assert result.code == 'stale_revision'

@pytest.mark.parametrize('offset,closed', [(-1,False),(0,True),(1,True)])
def test_expiry_boundary(data,offset,closed):
    result,new=run(buyer(data),now=data[1].expires_at+timedelta(microseconds=offset))
    assert (result.code=='closed') == closed
    assert (new is not None) == closed

def test_sold_elsewhere_closes(data):
    result,new=run(buyer(data),facts=data[3].model_copy(update={'available':False}))
    assert result.code=='closed' and new.state=='closed'

@pytest.mark.parametrize('change', [
    {'organization_id':uid(99)}, {'actor_id':uid(99)}, {'permitted':False}, {'seller_approved':False}])
def test_current_authority(data,change):
    result,new=run(data,authority=data[2].model_copy(update=change))
    assert result.state=='denied' and result.current is None and new is None

@pytest.mark.parametrize('change', [{'mode':'auction'},{'blocked':True},{'quote_current':False},
    {'subject_id':uid(99)},{'watch_id':uid(99)}])
def test_source_denial(data,change):
    result,_=run(data,facts=data[3].model_copy(update=change))
    assert result.state=='denied'

def test_exact_review_before_allocation(data):
    b=buyer(data)
    result,new=run(b)
    assert result.code=='allocation_required' and result.state=='pending' and new is None
    assert run(b,command=b[0].model_copy(update={'reviewed_revision':None}))[0].code=='review_current_fees'
    changed=b[0].economics.model_copy(update={'quote_revision':2})
    assert run(b,command=b[0].model_copy(update={'economics':changed}))[0].code=='review_current_fees'

def test_reject_no_reservation(data):
    result,new=run(buyer(data,'reject'))
    assert result.code=='rejected' and new.state=='rejected' and result.order_id is None

def test_wrong_role(data):
    assert run(data,command=data[0].model_copy(update={'kind':'accept'}))[0].state=='denied'
    assert run(buyer(data),command=buyer(data)[0].model_copy(update={'kind':'propose'}))[0].state=='denied'

@pytest.mark.parametrize('value',[True,1.2,0,-1,9_000_000_000_001])
def test_integer_money(data,value):
    with pytest.raises(ValidationError):
        Economics.model_validate({**data[0].economics.model_dump(),'price_minor':value})

def test_fee_rounding(data):
    econ=data[0].economics.model_copy(update={'price_minor':50,'buyer_fee_minor':2,
        'seller_commission_minor':3,'total_minor':52})
    assert run(data,command=data[0].model_copy(update={'economics':econ}),
        facts=data[3].model_copy(update={'economics':econ}))[0].state=='succeeded'

def test_incorrect_fee(data):
    econ=data[0].economics.model_copy(update={'buyer_fee_minor':0})
    assert run(data,command=data[0].model_copy(update={'economics':econ}),
        facts=data[3].model_copy(update={'economics':econ}))[0].state=='denied'

def test_timeout_pending_same_reference(data):
    class Timeout:
        async def execute(self,command,decision):
            raise TimeoutError
    result=asyncio.run(Counteroffers(Timeout()).command(data[0]))
    assert result.state=='pending' and result.operation_id==data[0].operation_id
    assert result.order_id is None

def test_lost_response_lookup_and_duplicate_contract(data):
    # Shared receipt fixture models a durable provider; connected restart remains owed.
    receipts={}
    class Provider:
        async def execute(self,c,decision):
            if c.operation_id in receipts:
                old,result=receipts[c.operation_id]
                if old!=c:
                    return Result(**c.model_dump(include={'operation_id','subject_id','watch_id','actor_id','organization_id','expected_revision'}),state='denied',code='operation_conflict',
                        revision=1,next_actor='seller')
                return result
            result,_=decision(c,*data[1:],NOW)
            receipts[c.operation_id]=(c,result)
            raise ConnectionError
        async def lookup(self,principal,subject,operation):
            if principal!=data[0].actor_id or subject!=data[0].subject_id:
                raise PermissionError
            return receipts[operation][1]
    c=data[0]
    assert asyncio.run(Counteroffers(Provider()).command(c)).state=='pending'
    restarted=Counteroffers(Provider())
    result=asyncio.run(restarted.operation(c.actor_id,c.subject_id,c.operation_id))
    assert result==asyncio.run(restarted.command(c)) and len(receipts)==1
    changed=c.model_copy(update={'expected_revision':2})
    assert asyncio.run(restarted.command(changed)).code=='operation_conflict'
    with pytest.raises(PermissionError):
        asyncio.run(restarted.operation(uid(99),c.subject_id,c.operation_id))

@pytest.mark.parametrize('field', ['source_revision','authority_revision'])
def test_stale_source_and_scope(data,field):
    assert run(data,command=data[0].model_copy(update={field:99}))[0].code=='stale_revision'

@pytest.mark.parametrize('kind', ['propose', 'accept', 'reject'])
def test_result_envelope_binds_command(data, kind):
    values = data if kind == 'propose' else buyer(data, kind)
    command = values[0]
    result, _ = run(values)
    fields = {'operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision'}
    assert result.model_dump(include=fields) == command.model_dump(include=fields)
    denied, _ = run(values, authority=values[2].model_copy(update={'permitted': False}))
    assert denied.current is None
    assert denied.model_dump(include=fields) == command.model_dump(include=fields)


def test_timeout_envelope_is_required(data):
    class Timeout:
        async def execute(self, command, decision):
            raise TimeoutError
    result = asyncio.run(Counteroffers(Timeout()).command(data[0]))
    for field in ['subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision']:
        assert getattr(result, field) == getattr(data[0], field)
        payload = result.model_dump()
        del payload[field]
        with pytest.raises(ValidationError):
            Result.model_validate(payload)
