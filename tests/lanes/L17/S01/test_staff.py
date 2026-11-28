import hashlib
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from bt_runtime.modules import discover

module, = discover(Path(__file__).resolve().parents[4] / 'services/service-operations/modules/maintenance-requests')
confirm = module.load('staff.py:confirm')
staff = sys.modules[confirm.__module__]
ACTOR, ORG, BUYER, WATCH, ORDER, RECEIPT, REQUEST, OP = [UUID(int=n) for n in range(1, 9)]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
@pytest.mark.parametrize('decision',['confirmed','rejected'])
async def test_precharge_confirmation_requires_exact_title_receipt_and_assignment(decision):
    command = staff.Confirmation(operation_id=OP, order_id=ORDER, assignment_revision=5, request_revision=1,
        watch_id=WATCH, watch_revision=2, custody_receipt_id=RECEIPT, custody_receipt_revision=3,
        incident_revision=0, decision=decision,reason='The reference differs from the watch received.' if decision=='rejected' else None)
    submitted = staff.MaintenanceRequest(schema_version='service.maintenance.v1', operation_id=UUID(int=91),
        actor_id=BUYER, subject_id=BUYER, watch_id=WATCH, watch_revision=1, organization_id=ORG,
        brand_id=ORG, capability_revision=1, policy_revision=1, expected_revision=0,
        intervention='limited_maintenance', reported_symptoms='Loses time', known_modifications='',
        photo_refs=[], limited_assessment_permission=True)
    row = {'watch_id':WATCH,'actor_id':BUYER,'private_request':submitted.model_dump_json(),
           'revision':1,'assignment_revision':5}
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    clock=now
    inside=False
    mode=None
    hold=None
    calls=[]
    expiry=None
    next_lock=False
    writes=[]
    pending=[]

    async def obtain(request,name,raw):
        nonlocal next_lock
        assert not inside and hold is not None
        calls.append(name)
        digest=hashlib.sha256(raw).hexdigest()
        if name=='maintenance_intake_grant_fence':
            fence=staff.IntakeGrantFence.model_validate_json(raw)
            assert fence.binding.model_dump()==dict(actor_id=ACTOR,organization_id=ORG,brand_id=ORG)
            async with transaction(None,lock_key=f'maintenance-staff:{REQUEST}'):
                for contender in ((UUID(int=111),hold[1]),(OP,'0'*64),None):
                    with pytest.raises(HTTPException) as other:
                        await staff.require_request_mutable(tx,REQUEST,predecision=contender)
                    assert other.value.detail=={'code':'maintenance_predecision_in_use'}
            if mode=='identity_missing':
                raise ConnectionError('identity_unavailable')
        else:
            assert name=='maintenance_precharge_custody_fence'
            fence=staff.OrdersPrechargeFence.model_validate_json(raw)
            assert fence.binding.model_dump()==command.model_dump(exclude={'reason','assignment_revision'})|dict(
                request_id=REQUEST,organization_id=ORG,brand_id=ORG)
            assert b'actor_id' not in raw and b'title_holder_id' not in raw and b'reason' not in raw
            next_lock=True
            if mode=='orders_missing':
                raise ConnectionError('orders_unavailable')
            if mode=='bare_false':
                return False
            if mode=='changed':
                return {'binding_hash':digest,'status':'changed'}
            if mode=='unbound_change':
                return {'binding_hash':'0'*64,'status':'changed'}
        assert fence.hold_until==hold[2]
        return {'binding_hash':'0'*64 if mode=='wrong_hash' else digest,
                'held_until':fence.hold_until-timedelta(milliseconds=1) if mode=='short' else fence.hold_until}

    async def fetchval(sql,*args):
        nonlocal hold
        if sql=='SELECT clock_timestamp()':
            return clock
        if sql.startswith('INSERT INTO maintenance_predecision_leases'):
            hold=args[1:]
            return hold[2]
        if 'FROM maintenance_predecision_leases' in sql:
            if not hold:
                return None
            if 'IS DISTINCT FROM' in sql:
                return hold[2]>clock and tuple(args[1:])!=hold[:2]
            return tuple(args[1:])==hold
        return None

    async def execute(sql,*args):
        nonlocal clock,hold
        if sql.startswith('INSERT'):
            pending.append((sql,*args))
        if sql.startswith('DELETE FROM maintenance_predecision_leases'):
            assert tuple(args[1:])==hold[:2]
            hold=None
        if expiry=='during_insert' and sql.startswith('INSERT INTO maintenance_assessment_decisions'):
            clock+=timedelta(seconds=5)

    source=AsyncMock(side_effect=obtain)
    tx=SimpleNamespace(fetchrow=AsyncMock(side_effect=lambda sql,*args: row if 'FROM maintenance_requests' in sql else None),
        fetchval=AsyncMock(side_effect=fetchval),
        execute=AsyncMock(side_effect=execute))

    @asynccontextmanager
    async def transaction(pool, *, lock_key):
        nonlocal inside,clock,next_lock,hold
        assert lock_key==f'maintenance-staff:{REQUEST}' and not inside
        if next_lock and expiry=='at_lock':
            clock+=timedelta(seconds=5)
        next_lock=False
        inside=True
        previous_hold=hold
        try:
            yield tx
            writes.extend(pending)
        except BaseException:
            hold=previous_hold
            raise
        finally:
            pending.clear()
            inside=False

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    with patch.multiple(staff, prerequisite=source, unit_of_work=transaction,
                        staff_grant=AsyncMock(return_value=staff.StaffGrant(actor_id=ACTOR, organization_id=ORG,can_assess=True,can_route=False))):
        for mode in ('identity_missing','orders_missing','bare_false','unbound_change','wrong_hash','short','changed'):
            with pytest.raises(HTTPException) as denied:
                await confirm(REQUEST,ORG,command,request,ACTOR)
            assert denied.value.status_code==(409 if mode=='changed' else 503) and not writes
            expected=['maintenance_intake_grant_fence']
            if mode not in ('identity_missing','wrong_hash','short'):
                expected.append('maintenance_precharge_custody_fence')
            assert calls==expected
            calls.clear()
        mode=None
        for expiry in ('at_lock','during_insert'):
            next_lock=False
            with pytest.raises(HTTPException) as elapsed:
                await confirm(REQUEST,ORG,command,request,ACTOR)
            assert elapsed.value.status_code==503 and not writes and hold[2]<=clock
        expiry=None
        result=await confirm(REQUEST,ORG,command,request,ACTOR)
        assert result['state']==decision and 'reason' not in result and len(writes)==2 and hold is None
        assert 'maintenance_assessment_decisions' in writes[0][0]
        assert 'maintenance_staff_operations' in writes[1][0]
        assert json.loads(writes[1][-2])['reason']==command.reason


@pytest.mark.anyio
async def test_scoped_confirmation_replay_does_not_acquire_a_case_mutation_guard():
    command=staff.Confirmation(operation_id=OP,order_id=ORDER,assignment_revision=5,request_revision=1,
        watch_id=WATCH,watch_revision=2,custody_receipt_id=RECEIPT,custody_receipt_revision=3,
        incident_revision=0,decision='confirmed')
    original={'state':'confirmed','operation_id':str(OP),'actor_id':str(ACTOR)}
    retained={'kind':'confirmation','actor_id':ACTOR,'organization_id':ORG,'request_id':REQUEST,
        'command':command.model_dump_json(),'receipt':json.dumps(original)}
    tx=SimpleNamespace(fetchrow=AsyncMock(return_value=retained),fetchval=AsyncMock(return_value=1),execute=AsyncMock())

    @asynccontextmanager
    async def transaction(pool,*,lock_key):
        assert lock_key==f'maintenance-staff:{REQUEST}'
        yield tx

    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    grant=AsyncMock(return_value=staff.StaffGrant(actor_id=ACTOR,organization_id=ORG,can_assess=True,can_route=False))
    no_change=AsyncMock(side_effect=HTTPException(409))
    case_lock=AsyncMock()
    source=AsyncMock()
    with patch.multiple(staff,unit_of_work=transaction,staff_grant=grant,require_mutable=no_change,lock_case=case_lock,prerequisite=source):
        assert await confirm(REQUEST,ORG,command,request,ACTOR)==original
        assert tx.fetchval.await_args.args[1:]==(REQUEST,ORG,ACTOR,5)
        tx.fetchval.return_value=None
        with pytest.raises(HTTPException) as reassigned:
            await confirm(REQUEST,ORG,command,request,ACTOR)
        assert reassigned.value.status_code==404
        no_change.assert_not_awaited();case_lock.assert_not_awaited();source.assert_not_awaited()
        grant.return_value=grant.return_value.model_copy(update={'can_assess':False})
        with pytest.raises(HTTPException) as revoked:
            await confirm(REQUEST,ORG,command,request,ACTOR)
        assert revoked.value.status_code==403


@pytest.mark.anyio
async def test_router_reads_reassignable_revision_without_assessor_evidence():
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value={'request_revision':2,'assignment_revision':5,'assessor_id':BUYER}),
        fetchval=AsyncMock(side_effect=[False,None,None,None,None,5]),execute=AsyncMock())

    @asynccontextmanager
    async def transaction(pool, *, lock_key):
        assert lock_key == f'maintenance-staff:{REQUEST}'
        yield tx

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    source = AsyncMock(return_value=staff.StaffGrant(actor_id=ACTOR,organization_id=ORG,can_assess=False,can_route=True))
    with patch.multiple(staff, unit_of_work=transaction, staff_grant=source):
        result = await staff.current_assignment(REQUEST,ORG,request,ACTOR)
        assert result.model_dump() == {'request_id':REQUEST,'organization_id':ORG,'request_revision':2,
                                       'assignment_revision':5,'assessor_id':BUYER}
        assert 'private_request' not in tx.fetchrow.await_args.args[0]
        router_grant = source.return_value
        source.side_effect = [router_grant,router_grant.model_copy(update={'can_assess':True})]
        tx.fetchrow.side_effect = [None,{'revision':result.request_revision}]
        change = staff.Assignment(operation_id=UUID(int=103),assessor_id=ACTOR,
            request_revision=result.request_revision,expected_revision=result.assignment_revision,
            reason='The original assessor is unavailable.')
        assigned = await staff.assign(REQUEST,ORG,change,request,ACTOR)
        assert assigned['revision']==6 and assigned['actor_id']==str(ACTOR)
        source.side_effect = None
        source.return_value = router_grant.model_copy(update={'can_route':False})
        with pytest.raises(HTTPException) as denied:
            await staff.current_assignment(REQUEST,ORG,request,ACTOR)
        assert denied.value.status_code == 404
        assert tx.fetchrow.await_count == 3


@pytest.mark.anyio
async def test_assessor_queue_is_resolved_from_local_assignments():
    actor = staff.StaffGrant(actor_id=ACTOR, organization_id=ORG,can_assess=True,can_route=False)
    tx = SimpleNamespace(fetch=AsyncMock(return_value=[{'request_id':REQUEST,'revision':9}]))

    @asynccontextmanager
    async def acquire(*, timeout):
        yield tx

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire))))
    with patch.object(staff, 'staff_grant', new=AsyncMock(return_value=actor)):
        queue = await staff.queue_access(request, ACTOR, ORG)
        assert not queue.routing_allowed and queue.request_ids == [REQUEST] and queue.assignment_revision == 9
        assert 'maintenance_assessment_assignments' in tx.fetch.await_args.args[0]
        assert tx.fetch.await_args.args[1:] == (ORG, ACTOR)


@pytest.mark.anyio
async def test_private_assignment_and_terminal_state_are_checked_in_authorized_transaction():
    grant = staff.StaffGrant(actor_id=ACTOR, organization_id=ORG,can_assess=True,can_route=False)
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value=None))
    with patch.object(staff, 'staff_grant', new=AsyncMock(return_value=grant)):
        assert await staff.assignment_access(None, ACTOR, ORG, REQUEST, tx) is False
    sql, *bound = tx.fetchrow.await_args.args
    assert bound == [REQUEST, ORG, ACTOR]
    assert 'a.assessor_id=$3' in sql and "d.state='rejected'" in sql
    assert 'r.revision=a.request_revision' in sql and 'FOR SHARE OF r,a' in sql


@pytest.mark.anyio
async def test_rejected_confirmation_lookup_requires_original_current_assessor():
    fixture = Path(__file__).resolve().parents[4] / 'packages/contracts-service/maintenance/staff-fixtures.json'
    data = json.loads(fixture.read_text())
    receipt = data['confirmation']['success'] | {'state':'rejected'}
    actor = UUID(receipt['actor_id'])
    request_id = UUID(receipt['request_id'])
    business = UUID(receipt['organization_id'])
    op = UUID(receipt['operation_id'])
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value={'kind':'confirmation','receipt':json.dumps(receipt),
        'assessor_id':actor,'assignment_revision':receipt['assignment_revision']}))

    @asynccontextmanager
    async def transaction(pool, *, lock_key):
        assert lock_key == f'maintenance-staff:{request_id}'
        yield tx

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    grant = staff.StaffGrant(actor_id=actor,organization_id=business,can_assess=True,can_route=False)
    with patch.multiple(staff, unit_of_work=transaction, staff_grant=AsyncMock(return_value=grant)):
        recovered = await staff.staff_operation(request_id, op, business, request, actor)
        assert recovered.state == 'rejected'
        tx.fetchrow.return_value['assignment_revision'] += 1
        with pytest.raises(HTTPException) as reassigned:
            await staff.staff_operation(request_id, op, business, request, actor)
        assert reassigned.value.status_code == 404


@pytest.mark.anyio
async def test_interactive_recovery_checks_current_deadline_before_any_receipt_or_mutation():
    check = module.load('routes.py:require_delivery_recovery')
    now = datetime(2026, 11, 24, tzinfo=timezone.utc)
    grant = AsyncMock(return_value=now)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        maintenance_delivery_operator_id=ACTOR, maintenance_provider=SimpleNamespace(delivery_authority_until=grant))))
    tx = SimpleNamespace(fetchval=AsyncMock(return_value=now), execute=AsyncMock())
    with pytest.raises(HTTPException) as expired:
        await check(request, ACTOR, tx)
    assert expired.value.status_code == 503
    tx.execute.assert_not_awaited()
    grant.return_value = None
    with pytest.raises(HTTPException) as revoked:
        await check(request, ACTOR, tx)
    assert revoked.value.status_code == 403
