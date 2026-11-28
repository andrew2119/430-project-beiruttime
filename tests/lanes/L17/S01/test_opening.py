from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID
import sys

import pytest
from fastapi import HTTPException
from bt_runtime.modules import discover

module, = discover(Path(__file__).resolve().parents[4] / 'services/service-operations/modules/maintenance-requests')
save = module.load('opening.py:save_preference')
opening = sys.modules[save.__module__]
REQUEST, BUYER, ORG, WATCH, OP, CHANGE = [UUID(int=n) for n in range(1,7)]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_buyer_preference_updates_without_implicitly_accepting_a_fee_and_replays():
    receipts = {}
    closures = {}
    locked = []

    class Store:
        async def fetchrow(self,sql,operation,request_id,buyer):
            assert 'INSERT INTO maintenance_preference_closures' in sql
            return closures.setdefault(operation,{'request_id':request_id,'buyer_id':buyer})

        async def fetchval(self, sql, identifier=None, *binding):
            if 'FROM maintenance_predecision_leases' in sql:
                assert binding==(None,None)
                return None
            if 'FROM maintenance_preference_closures' in sql:
                return identifier in closures
            if 'operation_id=$1' in sql:
                return receipts.get(identifier)
            if 'ORDER BY revision DESC' in sql:
                return next(reversed(receipts.values()),None)
            return None

        async def execute(self, sql, *args):
            if sql.startswith('INSERT INTO maintenance_opening_preferences'):
                receipts[args[0]] = args[3]
            elif 'pg_advisory_xact_lock' in sql:
                locked.append(args[0])

    @asynccontextmanager
    async def transaction(pool, *, lock_key):
        assert lock_key==f'maintenance-staff:{REQUEST}'
        yield Store()

    request=SimpleNamespace(method='GET',app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    scope=AsyncMock(return_value={'revision':1,'organization_id':ORG,'watch_id':WATCH})
    write=opening.Preference(operation_id=OP,request_revision=1,expected_revision=0,opening_permitted=True,no_polish=True)
    with patch.multiple(opening,unit_of_work=transaction,owned=scope):
        first=await save(REQUEST,write,request,BUYER)
        assert first.opening_permitted and first.no_polish and first.revision==1
        assert 'accepted_assessment_fee' not in first.model_dump()
        with pytest.raises(HTTPException) as changed:
            await save(REQUEST,write.model_copy(update={'no_polish':False}),request,BUYER)
        assert changed.value.status_code==409
        withdrawn=write.model_copy(update={'operation_id':CHANGE,'expected_revision':1,'opening_permitted':False})
        assert (await save(REQUEST,withdrawn,request,BUYER)).revision==2
        assert not (await opening.current_preference(REQUEST,request,BUYER)).opening_permitted
        assert await save(REQUEST,write,request,BUYER)==first
        assert await opening.preference_operation(REQUEST,OP,request,BUYER)==first
        with pytest.raises(HTTPException) as foreign:
            await opening.preference_operation(REQUEST,OP,request,ORG)
        assert foreign.value.status_code==404
        request.method='DELETE'
        assert await opening.preference_operation(REQUEST,OP,request,BUYER)==first
        missing=UUID(int=55)
        assert (await opening.preference_operation(REQUEST,missing,request,BUYER))['state']=='closed'
        with pytest.raises(HTTPException) as late:
            await save(REQUEST,write.model_copy(update={'operation_id':missing,'expected_revision':2}),request,BUYER)
        assert late.value.status_code==409
        assert len(receipts)==2 and len(locked)==9


@pytest.mark.anyio
async def test_history_checks_actual_title_even_when_destination_is_no_longer_eligible():
    staff_disposition = module.load('staff.py:buyer_disposition')
    staff = sys.modules[staff_disposition.__module__]
    provider=sys.modules[f'{staff.__package__}.provider']
    from test_maintenance import request as maintenance_request
    submitted=maintenance_request(actor_id=BUYER,subject_id=BUYER,organization_id=ORG,watch_id=WATCH)
    tx=SimpleNamespace(fetchrow=AsyncMock(return_value={'organization_id':ORG,'operation_id':OP,
        'private_request':submitted.model_dump_json(),'state':'rejected','command':'{"reason":"Serial did not match"}'}))

    @asynccontextmanager
    async def acquire(*,timeout):
        yield tx

    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire))))
    facts=AsyncMock(return_value={'actor_id':BUYER,'watch_id':WATCH,'title_holder_id':BUYER,'owned':True})
    with patch.object(provider,'prerequisite',facts):
        disposition=await staff_disposition(REQUEST,request,BUYER)
        assert disposition=={'request_id':str(REQUEST),'state':'rejected','reason':'Serial did not match'}
        facts.assert_awaited_once_with(request,'maintenance_historical_owner',BUYER,WATCH)
        facts.return_value={'actor_id':BUYER,'watch_id':WATCH,'title_holder_id':OP,'owned':False}
        with pytest.raises(HTTPException) as no_title:
            await staff_disposition(REQUEST,request,BUYER)
        assert no_title.value.status_code==404
        facts.side_effect=ConnectionError('unavailable')
        with pytest.raises(HTTPException) as outage:
            await staff_disposition(REQUEST,request,BUYER)
        assert outage.value.status_code==503


@pytest.mark.anyio
async def test_staff_acknowledges_only_exact_current_custody_consent_and_fee():
    import hashlib
    from datetime import datetime, timedelta, timezone
    staff, order, receipt, fee_operation, offer = [UUID(int=n) for n in range(20,25)]
    instant=datetime(2026,11,25,tzinfo=timezone.utc)
    preference=opening.PreferenceReceipt(operation_id=OP,request_revision=1,expected_revision=0,
        opening_permitted=False,no_polish=True,request_id=REQUEST,buyer_id=BUYER,organization_id=ORG,
        watch_id=WATCH,revision=1,recorded_at=instant)
    body=opening.Acknowledge(operation_id=CHANGE,request_revision=1,consent_revision=1,assignment_revision=3,
        order_id=order,receipt_id=receipt,receipt_revision=2,fee_acceptance_operation_id=fee_operation,
        offer_id=offer,offer_revision=4)
    row=dict(request_id=REQUEST,buyer_id=BUYER,watch_id=WATCH,revision=1,order_id=order,custody_receipt_id=receipt,
        custody_receipt_revision=2,watch_revision=5,incident_revision=1,assignment_revision=3)
    custody=dict(id=receipt,actor_id=staff,organization_id=ORG,order_id=order,revision=2,valid=True,
        watch_id=WATCH,watch_revision=5,incident_revision=1,received_at=instant,
        current_watch_id=WATCH,current_watch_revision=5,current_incident_revision=1)
    fee=dict(operation_id=fee_operation,request_id=REQUEST,request_revision=1,buyer_id=BUYER,
        organization_id=ORG,offer_id=offer,offer_revision=4,policy_revision=3,amount_minor=600,currency='USD',state='accepted',decided_at=instant)
    terms={k:v for k,v in fee.items() if k not in ('state','decided_at')}|{'order_id':order,'receipt_id':receipt,'watch_id':WATCH}
    saved=[]
    clock=instant
    changed=False
    wait=False
    stall=False
    deadlines=[]
    in_transaction=False
    assignment_lease_until=None
    fee_reads=0
    sampled=None
    opening_calls=0
    refresh_changed=False

    class Store:
        async def fetchrow(self,sql,*args):
            assert args[0]==ORG
            return row if args[1]==staff else None

        async def fetchval(self,sql,*args):
            nonlocal clock,sampled
            if sql=='SELECT clock_timestamp()':
                if not in_transaction:
                    sampled=clock
                return clock
            if "to_regclass('public.service_maintenance_request_leases')" in sql:
                return True
            if 'FROM service_maintenance_request_leases' in sql:
                assert args==(REQUEST,)
                return assignment_lease_until is not None and assignment_lease_until>clock
            if sql.startswith('INSERT'):
                saved.append(args[-1])
                if stall:
                    clock+=timedelta(seconds=4)
                return CHANGE
            if 'SELECT receipt FROM maintenance_opening_acknowledgements' in sql and saved:
                return saved[0]
            return None

        async def execute(self,sql,*args):
            if 'transaction_timeout' in sql:
                deadlines.append(args[0])

    @asynccontextmanager
    async def transaction(pool,*,lock_key):
        nonlocal in_transaction
        before=saved[:];in_transaction=True
        try:
            yield Store()
        except BaseException:
            saved[:]=before
            raise
        finally:
            in_transaction=False

    values={'intake_current_custody':custody,'maintenance_accepted_fee':fee,'maintenance_assessment_fee_binding':terms}
    async def source(request,name,*args):
        nonlocal clock,assignment_lease_until,fee_reads,opening_calls,sampled
        if name=='intake_current_custody':
            fee_reads=0;sampled=None
        if name=='maintenance_assessment_fee_binding':
            assert not in_transaction and args==(staff,ORG,order,receipt)
            fee_reads+=1
            if fee_reads==2:
                assert sampled==clock
                clock+=timedelta(milliseconds=150)
            # The Orders fee binding obtains this lease from the scoped assignment read.
            assignment_lease_until=clock+timedelta(seconds=5)
            if fee_reads==2 and refresh_changed:
                return terms|{'policy_revision':terms['policy_revision']+1}
        if name=='maintenance_opening_fence':
            assert not in_transaction and fee_reads==2
            opening_calls+=1
            raw,=args
            intent=opening.OpeningFenceRequest.model_validate_json(raw)
            assert intent.hold_until==sampled+timedelta(seconds=4)<assignment_lease_until
            assert intent.binding.operation_id==CHANGE and intent.binding.custody.incident_revision==1
            assert intent.binding.retained_fee.operation_id==fee_operation
            if changed:
                return False
            if wait:
                clock=intent.hold_until
            return {'binding_hash':hashlib.sha256(raw).hexdigest(), 'held_until':intent.hold_until}
        return values[name]

    @asynccontextmanager
    async def acquire(*,timeout):
        yield Store()

    request=SimpleNamespace(method='GET',app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire))))
    with patch.multiple(opening,unit_of_work=transaction,staff_grant=AsyncMock(return_value=SimpleNamespace(can_assess=True)),
                        owned=AsyncMock(return_value={'revision':1,'organization_id':ORG,'watch_id':WATCH}),
                        latest=AsyncMock(return_value=preference),prerequisite=source):
        values['maintenance_accepted_fee']=fee|{'offer_id':WATCH}
        with pytest.raises(HTTPException) as wrong_offer:
            await opening.acknowledge(REQUEST,ORG,body,request,staff)
        assert wrong_offer.value.status_code==409 and not saved
        values['maintenance_accepted_fee']=fee
        values['intake_current_custody']=custody|{'current_incident_revision':2}
        with pytest.raises(HTTPException) as damage:
            await opening.acknowledge(REQUEST,ORG,body,request,staff)
        assert damage.value.status_code==409 and not saved
        values['intake_current_custody']=custody
        review=await opening.intake_review(order,ORG,request,staff)
        assert not review.opening_permitted and review.no_polish and not review.acknowledged
        assert review.fee.operation_id==fee_operation and review.fee.amount_minor==600
        assert review.binding.model_dump()==body.model_dump(exclude={'operation_id'})
        refresh_changed=True
        with pytest.raises(HTTPException) as fee_rebound:
            await opening.acknowledge(REQUEST,ORG,body,request,staff)
        assert fee_rebound.value.status_code==409 and not saved and not opening_calls
        refresh_changed=False
        changed=True
        with pytest.raises(HTTPException) as invalidated:
            await opening.acknowledge(REQUEST,ORG,body,request,staff)
        assert invalidated.value.status_code==409 and not saved and not deadlines
        changed=False;wait=True
        with pytest.raises(HTTPException) as expired:
            await opening.acknowledge(REQUEST,ORG,body,request,staff)
        assert expired.value.status_code==503 and not saved and not deadlines
        wait=False;stall=True
        with pytest.raises(HTTPException) as late_write:
            await opening.acknowledge(REQUEST,ORG,body,request,staff)
        assert late_write.value.status_code==503 and not saved and deadlines==['2000ms']
        stall=False
        result=await opening.acknowledge(REQUEST,ORG,body,request,staff)
        assert result.accepted_assessment_fee and result.accepted_fee_minor==600
        assert not result.customer_opening_permission and result.no_polish and len(saved)==1
        assert assignment_lease_until>clock
        edit=opening.Preference(operation_id=UUID(int=99),request_revision=1,expected_revision=1,
            opening_permitted=True,no_polish=False)
        with pytest.raises(HTTPException) as superseding:
            await save(REQUEST,edit,request,BUYER)
        assert superseding.value.status_code==409
        assert superseding.value.detail=={'code':'maintenance_request_authority_in_use'} and len(saved)==1
        values.clear()
        assert await opening.acknowledge(REQUEST,ORG,body,request,staff)==result
        assert await opening.intake_operation(REQUEST,CHANGE,ORG,request,staff)==result
        with pytest.raises(HTTPException) as foreign:
            await opening.intake_operation(REQUEST,CHANGE,ORG,request,BUYER)
        assert foreign.value.status_code==404
