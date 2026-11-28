import hashlib
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.modules import discover
from bt_runtime.principal import CurrentPrincipal

module,=discover(Path(__file__).resolve().parents[4]/'services/service-operations/modules/maintenance-requests')
designate=module.load('destination.py:designate')
destination=sys.modules[designate.__module__]
ACTOR,ORG,BRAND,BUYER,ASSESSOR,RECOVERY,WATCH,REQUEST,OP,REVOKE=map(lambda i:UUID(int=i),range(1,11))


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_designator_requires_permission_in_the_exact_receiving_business():
    actor={'subject_id':ACTOR,'organization_id':ORG,'session_id':'designation-session'}
    grant={'organization_id':ORG,'permissions':['service.jobs.assign']}
    request=SimpleNamespace(query_params=SimpleNamespace(getlist=lambda name:[str(ORG)]))
    peer=AsyncMock(return_value=CurrentPrincipal.model_validate(dict(actor=actor,organizations=[ORG],
        organization_grants=[grant])))
    with patch.object(destination,'identity',peer):
        assert (await destination.designator(request,ORG)).subject_id==ACTOR
        for organization in (None,BRAND):
            peer.return_value=CurrentPrincipal.model_validate(dict(actor=actor,organizations=[ORG,BRAND],
                permissions=['service.jobs.assign'],organization_grants=[grant|{'organization_id':organization}] if organization else []))
            with pytest.raises(AccessDenied):
                await destination.designator(request,ORG)


@pytest.mark.anyio
@pytest.mark.parametrize('method',['get','replay'])
@pytest.mark.parametrize('change',['revoked','session_changed','none'])
async def test_private_designation_rechecks_scope_after_request_lock(method,change):
    command=destination.Designation(operation_id=OP,request_revision=1,assignment_revision=3,expected_revision=0,
        responsible_operator_id=RECOVERY)
    receipt=destination.DesignationReceipt(**command.model_dump(),request_id=REQUEST,organization_id=ORG,
        actor_id=ACTOR,revision=1)
    actor={'subject_id':ACTOR,'organization_id':ORG,'session_id':'original-session'}
    grant={'organization_id':ORG,'permissions':['service.jobs.assign']}
    request=SimpleNamespace(query_params=SimpleNamespace(getlist=lambda name:[str(ORG)]))
    locked=False
    checks=[]

    async def identity(request,organization):
        assert organization==ORG
        checks.append(locked)
        live=actor|{'session_id':'replacement-session'} if locked and change=='session_changed' else actor
        grants=[] if locked and change=='revoked' else [grant]
        return CurrentPrincipal.model_validate(dict(actor=live,organizations=[ORG],organization_grants=grants))

    tx=SimpleNamespace(fetchrow=AsyncMock(return_value=dict(request_id=REQUEST,organization_id=ORG,actor_id=ACTOR,
        command=command.model_dump_json(),receipt=receipt.model_dump_json())),execute=AsyncMock())

    @asynccontextmanager
    async def transaction(request,request_id):
        nonlocal locked
        assert request_id==REQUEST
        locked=True
        try:
            yield tx
        finally:
            locked=False

    scope=destination.DestinationBinding(request_id=REQUEST,organization_id=ORG,request_revision=1,buyer_id=BUYER,
        brand_id=BRAND,watch_id=WATCH,intervention='limited_maintenance',assessor_id=ASSESSOR,assignment_revision=3)
    read_scope=AsyncMock(return_value=scope)
    retained=AsyncMock(return_value=dict(request_revision=1,assignment_revision=3,revision=1,operator_id=RECOVERY))
    write_fence=AsyncMock(side_effect=AssertionError('private reads must not request a fresh write fence'))
    with patch.multiple(destination,identity=identity,confirmation_transaction=transaction,destination_scope=read_scope,
                        stored_designation=retained,qualify_destination=write_fence):
        selected=await destination.designator(request,ORG)
        result=(destination.current_designation(REQUEST,ORG,request,selected) if method=='get'
                else designate(REQUEST,ORG,command,request,selected))
        if change=='none':
            assert (await result).responsible_operator_id==RECOVERY
        else:
            with pytest.raises(AccessDenied if change=='revoked' else HTTPException):
                await result
            retained.assert_not_awaited()
        assert checks==[False,True]
        write_fence.assert_not_awaited()


@pytest.mark.anyio
async def test_destination_requires_retained_designation_and_independent_live_authority():
    now=datetime(2026,11,25,tzinfo=timezone.utc)
    clock=now
    assignment=3
    mode='healthy'
    reading=False
    held_until=now
    operations={}
    retained=None
    binding=destination.DestinationBinding(request_id=REQUEST,organization_id=ORG,request_revision=1,buyer_id=BUYER,
        brand_id=BRAND,watch_id=WATCH,intervention='limited_maintenance',assessor_id=ASSESSOR,assignment_revision=assignment)
    command=destination.Designation(operation_id=OP,request_revision=1,assignment_revision=assignment,expected_revision=0,
        responsible_operator_id=RECOVERY)
    actor=SimpleNamespace(subject_id=ACTOR,session_id='designation-session')

    class Tx:
        async def fetchrow(self,sql,*args):
            if 'SELECT * FROM maintenance_assessment_destination_operations' in sql:
                return operations.get(args[0])
            if 'SELECT d.revision' in sql:
                assert args==(REQUEST,ORG)
                return retained
            if 'FROM maintenance_assessment_assignments' in sql:
                assert args==(REQUEST,ORG)
                return dict(actor_id=BUYER,watch_id=WATCH,request_revision=1,brand_id=BRAND,
                    intervention='limited_maintenance',assessor_id=ASSESSOR,assignment_revision=assignment)
            raise AssertionError(sql)

        async def fetchval(self,sql,*args):
            if sql=='SELECT clock_timestamp()':
                return clock
            if 'SELECT revision FROM maintenance_assessment_destinations' in sql:
                return retained['revision'] if retained else None
            if 'maintenance_assessment_destinations' in sql:
                return held_until>clock
            return None

        async def execute(self,sql,*args):
            nonlocal retained,held_until
            if sql.startswith('INSERT INTO maintenance_assessment_destination_operations'):
                operation,request_id,who,org,body,receipt=args
                operations[operation]=dict(request_id=request_id,actor_id=who,organization_id=org,command=body,receipt=receipt)
            if sql.startswith('INSERT INTO maintenance_assessment_destinations'):
                _,_,request_revision,assignment_revision,revision,operator_id=args
                retained=dict(request_revision=request_revision,assignment_revision=assignment_revision,
                    revision=revision,operator_id=operator_id)
            if sql.startswith('UPDATE maintenance_assessment_destinations'):
                assert args[0]==REQUEST
                held_until=max(held_until,args[1])

    @asynccontextmanager
    async def transaction(request,request_id):
        assert request_id==REQUEST
        yield Tx()

    request=SimpleNamespace(state=SimpleNamespace())
    deadline=now+timedelta(seconds=4)
    envelope=destination.DestinationFence(schema_version=1,hold_until=deadline,binding=binding)
    raw=envelope.model_dump_json().encode()
    request.body=AsyncMock(return_value=raw)

    async def qualify(request,name,raw):
        assert name=='maintenance_destination_qualification_fence'
        decision=destination.DestinationQualificationFence.model_validate_json(raw)
        scope=decision.binding
        assert (scope.organization_id,scope.brand_id,scope.assessor_id)==(ORG,BRAND,ASSESSOR)
        assert scope.purpose=='maintenance_assessment_destination'
        assert decision.hold_until==clock+timedelta(seconds=4)
        if reading:
            assert scope.designator_id is None and scope.session_id is None
            assert scope.responsible_operator_id==RECOVERY
        else:
            assert scope.designator_id==ACTOR and scope.session_id=='designation-session'
        if mode=='unavailable':
            raise ConnectionError('not_current')
        return dict(binding_hash=hashlib.sha256(raw).hexdigest(),held_until=decision.hold_until,
            result=dict(seller_id=BRAND if mode=='substitute' else ORG,seller_type='dealer'))

    authorize=AsyncMock(side_effect=qualify)
    auth=Mock()
    current_identity=AsyncMock(return_value=CurrentPrincipal.model_validate(dict(
        actor=dict(subject_id=ACTOR,organization_id=ORG,session_id=actor.session_id),organizations=[ORG],
        organization_grants=[dict(organization_id=ORG,permissions=['service.jobs.assign'])])))
    with patch.multiple(destination,confirmation_transaction=transaction,prerequisite=authorize,service=auth,
                        identity=current_identity):
        with pytest.raises(PublicError) as waiting:
            await destination.assessment_destination(request)
        assert waiting.value.code=='maintenance_recovery_designation_pending'
        authorize.assert_not_awaited()
        with pytest.raises(HTTPException) as self_designation:
            await designate(REQUEST,ORG,command.model_copy(update={'responsible_operator_id':ASSESSOR}),request,actor)
        assert self_designation.value.status_code==409 and not operations
        mode='unavailable'
        with pytest.raises(HTTPException) as unqualified:
            await designate(REQUEST,ORG,command,request,actor)
        assert unqualified.value.status_code==503 and not operations
        mode='healthy'
        first=await designate(REQUEST,ORG,command,request,actor)
        assert first.revision==1 and first.responsible_operator_id==RECOVERY
        assert await designate(REQUEST,ORG,command,request,actor)==first and len(operations)==1
        assert (await destination.current_designation(REQUEST,ORG,request,actor)).responsible_operator_id==RECOVERY
        reading=True
        mode='substitute'
        with pytest.raises(HTTPException) as seller:
            await destination.assessment_destination(request)
        assert seller.value.status_code==503 and held_until==now
        mode='healthy'
        result=await destination.assessment_destination(request)
        assert result.binding_hash==hashlib.sha256(raw).hexdigest()
        assert result.result.model_dump()==dict(seller_id=ORG,responsible_operator_id=RECOVERY,seller_type='dealer')
        assert held_until==deadline
        auth.assert_called_with(request,{'service-operations'})
        revoke=command.model_copy(update={'operation_id':REVOKE,'expected_revision':1,'responsible_operator_id':None})
        reading=False
        with pytest.raises(HTTPException) as busy:
            await designate(REQUEST,ORG,revoke,request,actor)
        assert busy.value.detail=={'code':'maintenance_destination_in_use'} and len(operations)==1
        clock=deadline
        assignment+=1
        assert (await destination.current_designation(REQUEST,ORG,request,actor)).responsible_operator_id is None
        request.body.return_value=envelope.model_copy(update={'hold_until':clock+timedelta(seconds=4),
            'binding':binding.model_copy(update={'assignment_revision':assignment})}).model_dump_json().encode()
        with pytest.raises(PublicError) as stale:
            await destination.assessment_destination(request)
        assert stale.value.code=='maintenance_recovery_designation_pending'
        revoked=await designate(REQUEST,ORG,revoke.model_copy(update={'assignment_revision':assignment}),request,actor)
        assert revoked.revision==2 and revoked.responsible_operator_id is None
        with pytest.raises(PublicError) as still_waiting:
            await destination.assessment_destination(request)
        assert still_waiting.value.code=='maintenance_recovery_designation_pending'
