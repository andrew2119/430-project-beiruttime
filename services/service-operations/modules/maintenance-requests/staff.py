"""Current maintenance assignments and confirmed physical watch admission."""
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_contracts.service.maintenance.staff import (
    Assignment, AssignmentReceipt, Confirmation, ConfirmationReceipt, IntakeGrantBinding, IntakeGrantFence,
    MaintenanceFenceProof, OrdersPrechargeBinding, OrdersPrechargeFence, PrechargeFenceBinding, RoutingAssignment, StaffGrant,
)
from bt_contracts.service.intake.repair_fence import lock_case, require_mutable
from bt_contracts.service.maintenance.v1 import AssessmentAccess, AssessmentQueueAccess, Request as MaintenanceRequest
from bt_runtime.app.db import unit_of_work
from service_app.sources import prerequisite, service
from .lease import require_request_mutable
from .provider import Provider, buyer_identity, identity

router = APIRouter(tags=['maintenance assessment'])


async def staff_grant(request, actor, organization):
    try:
        grant = StaffGrant.model_validate(await prerequisite(request, 'maintenance_staff_grant', actor, organization))
    except (OSError, ValueError, KeyError):
        raise HTTPException(503) from None
    if (grant.actor_id, grant.organization_id) != (actor, organization):
        raise HTTPException(403)
    return grant


async def queue_access(request, actor, organization):
    grant = await staff_grant(request, actor, organization)
    if not (grant.can_route or grant.can_assess):
        raise HTTPException(403)
    async with request.app.state.pool.acquire(timeout=1) as tx:
        rows = await tx.fetch('''WITH epoch AS (
          SELECT coalesce(max(queue_epoch),1) AS revision FROM maintenance_assessment_assignments WHERE organization_id=$1
        ), assigned AS (
          SELECT a.request_id FROM maintenance_assessment_assignments a
          JOIN maintenance_requests r ON r.id=a.request_id AND r.revision=a.request_revision
          WHERE a.organization_id=$1 AND a.assessor_id=$2 LIMIT 10001
        ) SELECT e.revision,a.request_id FROM epoch e LEFT JOIN assigned a ON true''', organization, actor)
    if not rows or len(rows) > 10000:
        raise HTTPException(503)
    return AssessmentQueueAccess(actor_id=actor, organization_id=organization, assignment_revision=rows[0]['revision'],
        request_ids=[row['request_id'] for row in rows if row['request_id'] is not None], routing_allowed=grant.can_route)


async def assignment_access(request, actor, organization, request_id, tx):
    grant = await staff_grant(request, actor, organization)
    if not grant.can_assess:
        return False
    row = await tx.fetchrow('''SELECT r.private_request,r.revision,a.revision AS assignment_revision
        FROM maintenance_requests r JOIN maintenance_assessment_assignments a ON a.request_id=r.id
        WHERE r.id=$1 AND r.organization_id=$2 AND a.organization_id=$2 AND a.assessor_id=$3
          AND r.revision=a.request_revision AND NOT EXISTS (SELECT 1 FROM maintenance_assessment_decisions d
              WHERE d.request_id=r.id AND d.state='rejected') FOR SHARE OF r,a''', request_id, organization, actor)
    if not row:
        return False
    command = MaintenanceRequest.model_validate_json(row['private_request'])
    return AssessmentAccess(request_id=request_id, actor_id=actor, organization_id=organization,
        watch_id=command.watch_id, brand_id=command.brand_id, intervention=command.intervention,
        request_revision=row['revision'], assignment_revision=row['assignment_revision'],
        capability_revision=command.capability_revision, allowed=True)


async def selected(request: Request, organization_id: UUID):
    if len(request.query_params.getlist('organization_id')) != 1:
        raise HTTPException(422)
    return (await identity(request, organization_id)).actor.subject_id


async def replay(tx, kind, actor, organization, request_id, body):
    op = await tx.fetchrow('SELECT * FROM maintenance_staff_operations WHERE operation_id=$1', body.operation_id)
    if not op:
        return None
    if (op['kind'], op['actor_id'], op['organization_id'], op['request_id']) != (kind, actor, organization, request_id):
        raise HTTPException(404)
    if json.loads(op['command']) != body.model_dump(mode='json'):
        raise HTTPException(409)
    return json.loads(op['receipt'])


async def store(tx, kind, actor, organization, request_id, body, receipt):
    await tx.execute('INSERT INTO maintenance_staff_operations VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb)',
        body.operation_id, request_id, actor, organization, kind, body.model_dump_json(), json.dumps(receipt))


async def lock_operation(tx, operation_id):
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'maintenance-staff-operation:{operation_id}')


@router.get('/v1/maintenance/requests/{request_id}/assignment', response_model=RoutingAssignment)
async def current_assignment(request_id: UUID, organization_id: UUID, request: Request, actor=Depends(selected)):
    async with unit_of_work(request.app.state.pool, lock_key=f'maintenance-staff:{request_id}') as tx:
        if not (await staff_grant(request, actor, organization_id)).can_route:
            raise HTTPException(404)
        row = await tx.fetchrow('''SELECT r.revision AS request_revision, coalesce(a.revision,0) AS assignment_revision, a.assessor_id
            FROM maintenance_requests r JOIN maintenance_assessment_inbox i ON i.request_id=r.id AND i.organization_id=r.organization_id
            LEFT JOIN maintenance_assessment_assignments a ON a.request_id=r.id AND a.organization_id=r.organization_id
            WHERE r.id=$1 AND r.organization_id=$2 AND NOT EXISTS (
              SELECT 1 FROM maintenance_assessment_decisions d WHERE d.request_id=r.id)''', request_id, organization_id)
        if row is None:
            raise HTTPException(404)
        return RoutingAssignment(request_id=request_id, organization_id=organization_id, **dict(row))


@router.post('/v1/maintenance/requests/{request_id}/assignment', response_model=AssignmentReceipt)
async def assign(request_id: UUID, organization_id: UUID, body: Assignment, request: Request, actor=Depends(selected)):
    async with unit_of_work(request.app.state.pool, lock_key=f'maintenance-staff:{request_id}') as tx:
        if not (await staff_grant(request, actor, organization_id)).can_route:
            raise HTTPException(403)
        await lock_operation(tx, body.operation_id)
        old = await replay(tx, 'assignment', actor, organization_id, request_id, body)
        if old is not None:
            return old
        await require_request_mutable(tx,request_id)
        case = await tx.fetchval('SELECT case_id FROM maintenance_received_cases WHERE request_id=$1', request_id)
        if case is not None:
            await lock_case(tx, case)
            await require_mutable(tx, case)
        retained = await tx.fetchrow('''SELECT r.revision FROM maintenance_requests r
            JOIN maintenance_assessment_inbox i ON i.request_id=r.id AND i.organization_id=r.organization_id
            WHERE r.id=$1 AND r.organization_id=$2 FOR SHARE OF r''', request_id, organization_id)
        if not retained:
            raise HTTPException(404)
        if retained['revision'] != body.request_revision or await tx.fetchval(
                'SELECT 1 FROM maintenance_assessment_decisions WHERE request_id=$1', request_id):
            raise HTTPException(409)
        prior = await tx.fetchval('SELECT revision FROM maintenance_assessment_assignments WHERE request_id=$1', request_id)
        if (prior or 0) != body.expected_revision:
            raise HTTPException(409)
        if not (await staff_grant(request, body.assessor_id, organization_id)).can_assess:
            raise HTTPException(403)
        revision = body.expected_revision + 1
        await tx.execute('''INSERT INTO maintenance_assessment_assignments
            (request_id,organization_id,assessor_id,revision,request_revision) VALUES($1,$2,$3,$4,$5)
            ON CONFLICT(request_id) DO UPDATE SET assessor_id=excluded.assessor_id,
                revision=excluded.revision,request_revision=excluded.request_revision,queue_epoch=excluded.queue_epoch,
                changed_at=clock_timestamp()''',
            request_id, organization_id, body.assessor_id, revision, body.request_revision)
        receipt = {'operation_id':str(body.operation_id),'request_id':str(request_id), 'organization_id':str(organization_id),
                   'actor_id':str(actor), 'assessor_id':str(body.assessor_id), 'revision':revision,
                   'request_revision':body.request_revision}
        await store(tx, 'assignment', actor, organization_id, request_id, body, receipt)
    return receipt


async def confirmation_replay(tx, request, request_id, organization, actor, body):
    await lock_operation(tx,body.operation_id)
    if not (await staff_grant(request,actor,organization)).can_assess:
        raise HTTPException(403)
    old=await replay(tx,'confirmation',actor,organization,request_id,body)
    if old is None:
        return None
    assigned=await tx.fetchval('''SELECT 1 FROM maintenance_requests r
        JOIN maintenance_assessment_assignments a ON a.request_id=r.id AND a.organization_id=r.organization_id
            AND a.request_revision=r.revision
        WHERE r.id=$1 AND r.organization_id=$2 AND a.assessor_id=$3 AND a.revision=$4''',
        request_id,organization,actor,body.assignment_revision)
    if not assigned:
        raise HTTPException(404)
    return old


async def confirmation_binding(tx, request, request_id, organization, actor, body):
    row=await tx.fetchrow('''SELECT r.watch_id,r.actor_id,r.private_request,r.revision,a.revision AS assignment_revision
        FROM maintenance_requests r JOIN maintenance_assessment_assignments a ON a.request_id=r.id
         AND a.request_revision=r.revision AND a.organization_id=r.organization_id
        WHERE r.id=$1 AND r.organization_id=$2 AND a.assessor_id=$3 AND r.state='submitted'
        FOR SHARE OF r,a''',request_id,organization,actor)
    if not row:
        raise HTTPException(404)
    if (row['watch_id'],row['revision'],row['assignment_revision'])!=(body.watch_id,body.request_revision,body.assignment_revision):
        raise HTTPException(409)
    if await tx.fetchval('SELECT 1 FROM maintenance_assessment_decisions WHERE request_id=$1',request_id):
        raise HTTPException(409)
    retained=MaintenanceRequest.model_validate_json(row['private_request'])
    if row['actor_id']==actor:
        raise HTTPException(403)
    if retained.brand_id!=organization and not (await staff_grant(request,actor,retained.brand_id)).can_assess:
        raise HTTPException(403)
    return PrechargeFenceBinding(**body.model_dump(exclude={'reason'}),request_id=request_id,organization_id=organization,
        actor_id=actor,title_holder_id=row['actor_id'],brand_id=retained.brand_id)


async def peer_coverage(request,name,envelope,deadline,*,latest,changed=False):
    raw=envelope.model_dump_json().encode()
    try:
        answer=await prerequisite(request,name,raw)
        digest=hashlib.sha256(raw).hexdigest()
        if changed and answer=={'binding_hash':digest,'status':'changed'}:
            raise HTTPException(409,detail={'code':'maintenance_precharge_changed'})
        proof=MaintenanceFenceProof.model_validate(answer)
        if (proof.binding_hash!=digest or proof.held_until.utcoffset()!=timedelta(0) or
                not deadline<=proof.held_until<=latest):
            raise ValueError('maintenance_fence_binding')
    except (OSError,ValueError,KeyError):
        raise HTTPException(503) from None


async def precharge_fences(request,now,deadline,binding):
    scope=IntakeGrantBinding(actor_id=binding.actor_id,organization_id=binding.organization_id,brand_id=binding.brand_id)
    await peer_coverage(request,'maintenance_intake_grant_fence',
        IntakeGrantFence(schema_version=1,hold_until=deadline,binding=scope),deadline,latest=now+timedelta(seconds=5))
    custody=OrdersPrechargeBinding.model_validate(binding.model_dump(include=set(OrdersPrechargeBinding.model_fields)))
    await peer_coverage(request,'maintenance_precharge_custody_fence',
        OrdersPrechargeFence(schema_version=1,hold_until=deadline,binding=custody),deadline,
        latest=now+timedelta(seconds=5),changed=True)


def predecision_hash(binding,body):
    return hashlib.sha256((binding.model_dump_json()+'\n'+body.model_dump_json()).encode()).hexdigest()


async def keep_predecision(tx,request_id,operation,digest,deadline):
    held=await tx.fetchval('''INSERT INTO maintenance_predecision_leases(request_id,operation_id,binding_hash,held_until)
        VALUES($1,$2,$3,$4) ON CONFLICT(request_id) DO UPDATE SET operation_id=EXCLUDED.operation_id,
        binding_hash=EXCLUDED.binding_hash,held_until=GREATEST(maintenance_predecision_leases.held_until,EXCLUDED.held_until)
        WHERE maintenance_predecision_leases.held_until<=clock_timestamp() OR
              (maintenance_predecision_leases.operation_id,maintenance_predecision_leases.binding_hash)=($2,$3)
        RETURNING held_until''',request_id,operation,digest,deadline)
    if held is None or held<deadline:
        raise HTTPException(409,detail={'code':'maintenance_predecision_in_use'})


async def precharge_remaining(tx,deadline):
    now=await tx.fetchval('SELECT clock_timestamp()')
    remaining=int((deadline-now-timedelta(seconds=1)).total_seconds()*1000)
    if remaining<=0:
        raise HTTPException(503)
    return remaining


@asynccontextmanager
async def confirmation_transaction(request,request_id):
    try:
        async with unit_of_work(request.app.state.pool,lock_key=f'maintenance-staff:{request_id}') as tx:
            yield tx
    except (asyncpg.PostgresError,asyncpg.InterfaceError,OSError):
        raise HTTPException(503) from None


@router.post('/v1/maintenance/requests/{request_id}/watch-confirmation', response_model=ConfirmationReceipt)
async def confirm(request_id: UUID, organization_id: UUID, body: Confirmation, request: Request, actor=Depends(selected)):
    async with confirmation_transaction(request,request_id) as tx:
        old=await confirmation_replay(tx,request,request_id,organization_id,actor,body)
        if old is not None:
            return old
        binding=await confirmation_binding(tx,request,request_id,organization_id,actor,body)
        digest=predecision_hash(binding,body)
        await require_request_mutable(tx,request_id,predecision=(body.operation_id,digest))
        now=await tx.fetchval('SELECT clock_timestamp()')
        deadline=now+timedelta(seconds=4)
        await keep_predecision(tx,request_id,body.operation_id,digest,deadline)
    # Each independent owner sees only its exact scope; no remote call retains the local lock.
    await precharge_fences(request,now,deadline,binding)
    async with confirmation_transaction(request,request_id) as tx:
        old=await confirmation_replay(tx,request,request_id,organization_id,actor,body)
        if old is not None:
            return old
        await require_request_mutable(tx,request_id,predecision=(body.operation_id,digest))
        case=await tx.fetchval('SELECT case_id FROM maintenance_received_cases WHERE request_id=$1',request_id)
        if case is not None:
            await lock_case(tx,case)
            await require_mutable(tx,case)
        if await confirmation_binding(tx,request,request_id,organization_id,actor,body)!=binding:
            raise HTTPException(409)
        if not await tx.fetchval('''SELECT 1 FROM maintenance_predecision_leases WHERE request_id=$1
                AND operation_id=$2 AND binding_hash=$3 AND held_until>=$4''',request_id,body.operation_id,digest,deadline):
            raise HTTPException(503)
        remaining=await precharge_remaining(tx,deadline)
        await tx.execute("SELECT set_config('transaction_timeout', $1, true)",f'{min(remaining,2000)}ms')
        await tx.execute('''INSERT INTO maintenance_assessment_decisions
          (request_id,actor_id,organization_id,watch_id,assignment_revision,request_revision,
           custody_receipt_id,custody_receipt_revision,order_id,watch_revision,incident_revision,state)
          VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)''',
            request_id, actor, organization_id, body.watch_id, body.assignment_revision, body.request_revision,
            body.custody_receipt_id,body.custody_receipt_revision,body.order_id,body.watch_revision,body.incident_revision,body.decision)
        receipt={**body.model_dump(mode='json',exclude={'reason','decision'}),'actor_id':str(actor),
                 'request_id':str(request_id),'organization_id':str(organization_id),'state':body.decision}
        await store(tx, 'confirmation', actor, organization_id, request_id, body, receipt)
        await tx.execute('DELETE FROM maintenance_predecision_leases WHERE request_id=$1 AND operation_id=$2 AND binding_hash=$3',
            request_id,body.operation_id,digest)
        await precharge_remaining(tx,deadline)
    return receipt


@router.get('/v1/maintenance/requests/{request_id}/staff-operations/{operation_id}',
            response_model=AssignmentReceipt | ConfirmationReceipt)
async def staff_operation(request_id: UUID, operation_id: UUID, organization_id: UUID,
                          request: Request, actor=Depends(selected)):
    async with unit_of_work(request.app.state.pool, lock_key=f'maintenance-staff:{request_id}') as tx:
        grant = await staff_grant(request, actor, organization_id)
        if not (grant.can_route or grant.can_assess):
            raise HTTPException(404)
        row = await tx.fetchrow('''SELECT o.kind,o.receipt,a.assessor_id,a.revision AS assignment_revision
            FROM maintenance_staff_operations o LEFT JOIN maintenance_assessment_assignments a
              ON a.request_id=o.request_id AND a.organization_id=o.organization_id
            WHERE o.operation_id=$1 AND o.request_id=$2 AND o.actor_id=$3 AND o.organization_id=$4''',
            operation_id, request_id, actor, organization_id)
        if row is None:
            raise HTTPException(404)
        receipt = json.loads(row['receipt'])
        if row['kind'] == 'assignment' and grant.can_route:
            return AssignmentReceipt.model_validate(receipt)
        if (row['kind'] == 'confirmation' and grant.can_assess and row['assessor_id'] == actor
                and row['assignment_revision'] == receipt.get('assignment_revision')):
            # Historical decision acknowledgement only; it includes no private notes or photos.
            return ConfirmationReceipt.model_validate(receipt)
        raise HTTPException(404)


@router.get('/v1/maintenance/requests/{request_id}/disposition')
async def buyer_disposition(request_id: UUID, request: Request, buyer=Depends(buyer_identity)):
    async with request.app.state.pool.acquire(timeout=1) as tx:
        row = await tx.fetchrow('''SELECT r.organization_id,r.operation_id,r.private_request,d.state,o.command
            FROM maintenance_requests r LEFT JOIN maintenance_assessment_decisions d ON d.request_id=r.id
            LEFT JOIN maintenance_staff_operations o ON o.request_id=r.id AND o.kind='confirmation'
            WHERE r.id=$1 AND r.actor_id=$2''', request_id, buyer)
    if row is None:
        raise HTTPException(404)
    submitted = MaintenanceRequest.model_validate_json(row['private_request'])
    try:
        allowed = await Provider(request).operation_access(buyer, row['organization_id'], row['operation_id'],
            submitted.watch_id, submitted.intervention, submitted.brand_id)
    except (ValueError, OSError, KeyError):
        raise HTTPException(503) from None
    if allowed is not True:
        raise HTTPException(404)
    state = row['state'] or 'awaiting_confirmation'
    result = {'request_id': str(request_id), 'state': state}
    if state == 'rejected' and row['command']:
        result['reason'] = json.loads(row['command'])['reason']
    return result


@router.get('/internal/v1/maintenance/requests/{request_id}/watch-confirmation')
async def confirmation(request_id: UUID, request: Request, organization_id: UUID, watch_id: UUID, order_id: UUID):
    service(request, {'orders', 'pricing'})
    async with request.app.state.pool.acquire(timeout=1) as tx:
        value = await tx.fetchrow('''SELECT state,request_id,organization_id,watch_id,order_id,request_revision,
            custody_receipt_id,custody_receipt_revision,watch_revision,incident_revision,recorded_at
            FROM maintenance_assessment_decisions WHERE request_id=$1 AND organization_id=$2 AND watch_id=$3 AND order_id=$4''',
            request_id, organization_id, watch_id, order_id)
    if value is None:
        raise HTTPException(409)
    return dict(value)
