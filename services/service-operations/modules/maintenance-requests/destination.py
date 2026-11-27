"""Audited receiving-business recovery designation and bounded reservation authority."""
import hashlib
import json
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from bt_contracts.service.maintenance.destination import (
    CurrentDesignation, Designation, DesignationReceipt, Destination, DestinationBinding, DestinationFence, DestinationProof,
    DestinationQualification, DestinationQualificationFence, DestinationQualificationProof,
)
from bt_contracts_core.errors import PublicError
from bt_runtime.principal import require_scope
from service_app.sources import prerequisite, service
from .lease import require_request_mutable
from .provider import identity
from .staff import confirmation_transaction, lock_operation, precharge_remaining

router=APIRouter(tags=['maintenance destination'])


async def designator(request:Request,organization_id:UUID):
    if len(request.query_params.getlist('organization_id'))!=1:
        raise HTTPException(422)
    return await current_designator(request,organization_id)


async def current_designator(request,organization_id,original=None):
    principal=await identity(request,organization_id)
    require_scope(principal,'service.jobs.assign',organization_id)
    actor=principal.actor
    if original is not None and (actor.subject_id,actor.organization_id,actor.session_id)!=(
            original.subject_id,organization_id,original.session_id):
        raise HTTPException(403)
    return actor


async def destination_scope(tx,request_id,organization):
    row=await tx.fetchrow('''SELECT r.actor_id,r.watch_id,r.revision AS request_revision,
               r.private_request->>'brand_id' AS brand_id,r.private_request->>'intervention' AS intervention,
               a.assessor_id,a.revision AS assignment_revision
        FROM maintenance_assessment_assignments a JOIN maintenance_requests r ON r.id=a.request_id
        JOIN maintenance_request_operations o ON o.operation_id=r.operation_id
            AND o.actor_id=r.actor_id AND o.organization_id=r.organization_id
        WHERE r.id=$1 AND r.organization_id=$2 AND r.state='submitted'
            AND a.organization_id=r.organization_id AND a.request_revision=r.revision
            AND o.result @> jsonb_build_object('request_id',r.id,'revision',r.revision,'watch_id',r.watch_id)
            AND NOT EXISTS(SELECT 1 FROM maintenance_assessment_decisions WHERE request_id=r.id)
        FOR SHARE OF r,a''',request_id,organization)
    if row is None:
        raise HTTPException(409)
    return DestinationBinding(request_id=request_id,organization_id=organization,buyer_id=row['actor_id'],
        **{field:row[field] for field in ('brand_id','watch_id','intervention','request_revision','assessor_id','assignment_revision')})


async def qualify_destination(request,scope,recovery,now,deadline,*,actor=None):
    if recovery is not None and recovery in (scope.buyer_id,scope.assessor_id,scope.organization_id):
        raise HTTPException(409)
    try:
        qualified=DestinationQualification(organization_id=scope.organization_id,brand_id=scope.brand_id,
            intervention=scope.intervention,assessor_id=scope.assessor_id,responsible_operator_id=recovery,
            designator_id=actor.subject_id if actor else None,session_id=actor.session_id if actor else None)
        raw=DestinationQualificationFence(schema_version=1,hold_until=deadline,binding=qualified).model_dump_json().encode()
        proof=DestinationQualificationProof.model_validate(await prerequisite(request,'maintenance_destination_qualification_fence',raw))
        if (proof.binding_hash!=hashlib.sha256(raw).hexdigest() or proof.held_until.utcoffset()!=timedelta(0)
                or not deadline<=proof.held_until<=now+timedelta(seconds=5)
                or proof.result.seller_id!=scope.organization_id
                or (proof.result.seller_type=='brand')!=(scope.brand_id==scope.organization_id)):
            raise ValueError('maintenance_destination_binding')
    except (OSError,ValueError,KeyError):
        raise HTTPException(503) from None
    return proof.result


async def stored_designation(tx,scope):
    return await tx.fetchrow('''SELECT d.revision,d.request_revision,d.assignment_revision,d.operator_id
        FROM maintenance_assessment_destinations d
        JOIN maintenance_assessment_destination_operations o ON o.operation_id=d.operation_id AND o.request_id=d.request_id
        WHERE d.request_id=$1 AND o.organization_id=$2
            AND o.receipt @> jsonb_build_object('responsible_operator_id',d.operator_id,'revision',d.revision,
                'request_revision',d.request_revision,'assignment_revision',d.assignment_revision)''',
        scope.request_id,scope.organization_id)


def current_operator(retained,scope):
    if retained and (retained['request_revision'],retained['assignment_revision'])==(scope.request_revision,scope.assignment_revision):
        return retained['operator_id']
    return None


@router.get('/v1/maintenance/requests/{request_id}/recovery-designation',response_model=CurrentDesignation)
async def current_designation(request_id:UUID,organization_id:UUID,request:Request,actor=Depends(designator)):
    async with confirmation_transaction(request,request_id) as tx:
        await current_designator(request,organization_id,actor)
        scope=await destination_scope(tx,request_id,organization_id)
        retained=await stored_designation(tx,scope)
        return CurrentDesignation(request_id=request_id,organization_id=organization_id,request_revision=scope.request_revision,
            assignment_revision=scope.assignment_revision,revision=retained['revision'] if retained else 0,
            responsible_operator_id=current_operator(retained,scope))


@router.post('/v1/maintenance/requests/{request_id}/recovery-designation',response_model=DesignationReceipt)
async def designate(request_id:UUID,organization_id:UUID,body:Designation,request:Request,actor=Depends(designator)):
    async with confirmation_transaction(request,request_id) as tx:
        await lock_operation(tx,body.operation_id)
        prior=await tx.fetchrow('SELECT * FROM maintenance_assessment_destination_operations WHERE operation_id=$1',body.operation_id)
        if prior:
            await current_designator(request,organization_id,actor)
            if (prior['request_id'],prior['organization_id'],prior['actor_id'])!=(request_id,organization_id,actor.subject_id):
                raise HTTPException(404)
            if json.loads(prior['command'])!=body.model_dump(mode='json'):
                raise HTTPException(409)
            return DesignationReceipt.model_validate_json(prior['receipt'])
        await require_request_mutable(tx,request_id)
        current=await destination_scope(tx,request_id,organization_id)
        revision=await tx.fetchval('SELECT revision FROM maintenance_assessment_destinations WHERE request_id=$1',request_id) or 0
        if (current.request_revision,current.assignment_revision,revision)!=(body.request_revision,body.assignment_revision,body.expected_revision):
            raise HTTPException(409)
        now=await tx.fetchval('SELECT clock_timestamp()')
        deadline=now+timedelta(seconds=4)
        # Identity fences only its own qualification and business records; it never re-enters this lock.
        await qualify_destination(request,current,body.responsible_operator_id,now,deadline,actor=actor)
        remaining=await precharge_remaining(tx,deadline)
        await tx.execute("SELECT set_config('transaction_timeout',$1,true)",f'{min(remaining,2000)}ms')
        receipt=DesignationReceipt(**body.model_dump(),request_id=request_id,organization_id=organization_id,
            actor_id=actor.subject_id,revision=revision+1)
        await tx.execute('''INSERT INTO maintenance_assessment_destination_operations
            (operation_id,request_id,actor_id,organization_id,command,receipt) VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb)''',
            body.operation_id,request_id,actor.subject_id,organization_id,body.model_dump_json(),receipt.model_dump_json())
        await tx.execute('''INSERT INTO maintenance_assessment_destinations
            (request_id,operation_id,request_revision,assignment_revision,revision,operator_id) VALUES($1,$2,$3,$4,$5,$6)
            ON CONFLICT(request_id) DO UPDATE SET operation_id=excluded.operation_id,request_revision=excluded.request_revision,
            assignment_revision=excluded.assignment_revision,revision=excluded.revision,operator_id=excluded.operator_id''',
            request_id,body.operation_id,body.request_revision,body.assignment_revision,receipt.revision,body.responsible_operator_id)
        await precharge_remaining(tx,deadline)
        return receipt


async def fence_destination(tx,request,body:DestinationFence,raw:bytes):
    """Use the caller's maintenance-staff transaction; never loop back over HTTP with that lock held."""
    scope,deadline=body.binding,body.hold_until
    now=await tx.fetchval('SELECT clock_timestamp()')
    if deadline.utcoffset()!=timedelta(0) or not now<deadline<=now+timedelta(seconds=5):
        raise HTTPException(503)
    if await destination_scope(tx,scope.request_id,scope.organization_id)!=scope:
        raise HTTPException(409)
    recovery=current_operator(await stored_designation(tx,scope),scope)
    if recovery is None:
        raise PublicError('maintenance_recovery_designation_pending','Waiting for the receiving business to designate a recovery operator.',status=503)
    qualified=await qualify_destination(request,scope,recovery,now,deadline)
    remaining=await precharge_remaining(tx,deadline)
    await tx.execute("SELECT set_config('transaction_timeout',$1,true)",f'{min(remaining,2000)}ms')
    await tx.execute('''UPDATE maintenance_assessment_destinations SET held_until=GREATEST(held_until,$2)
        WHERE request_id=$1''',scope.request_id,deadline)
    await precharge_remaining(tx,deadline)
    return DestinationProof(binding_hash=hashlib.sha256(raw).hexdigest(),held_until=deadline,
        result=Destination(**qualified.model_dump(),responsible_operator_id=recovery))


@router.post('/internal/v1/maintenance-assessment-destination-fences',response_model=DestinationProof)
async def assessment_destination(request:Request):
    service(request,{'service-operations'})
    raw=await request.body()
    if len(raw)>4096:
        raise HTTPException(413)
    try:
        body=DestinationFence.model_validate_json(raw)
    except ValueError:
        raise HTTPException(422) from None
    async with confirmation_transaction(request,body.binding.request_id) as tx:
        return await fence_destination(tx,request,body,raw)
