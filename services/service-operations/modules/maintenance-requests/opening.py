"""Bound buyer preference and intake receipt acknowledgement for a maintenance assessment."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from bt_contracts.service.intake.current import CurrentCustodyReceipt
from bt_contracts.service.intake.repair_fence import lock_case, require_mutable
from bt_contracts.service.maintenance.opening import (
    Acknowledge, AcceptedFee, AcknowledgementBinding, AssessmentFeeBinding, IntakeOpeningReview,
    OpeningAcknowledgement, OpeningFenceBinding, OpeningFenceRequest, OpeningFenceResult, Preference, PreferenceReceipt,
)
from bt_runtime.app.db import unit_of_work
from bt_contracts_core.errors import PublicError
from service_app.sources import prerequisite, service
from .lease import require_request_mutable
from .provider import Provider, buyer_identity
from .staff import lock_operation, selected, staff_grant

router = APIRouter()


def decoded(row):
    return json.loads(row) if isinstance(row,str) else row


async def owned(tx, request_id, buyer, request):
    row = await tx.fetchrow('''SELECT r.*, r.private_request->>'intervention' AS intervention,
        r.private_request->>'brand_id' AS brand_id FROM maintenance_requests r
        WHERE r.id=$1 AND r.actor_id=$2 AND r.state='submitted' ''',request_id,buyer)
    if not row:
        raise HTTPException(404)
    try:
        allowed = await Provider(request).operation_access(buyer,row['organization_id'],row['operation_id'],
            row['watch_id'],row['intervention'],UUID(row['brand_id']))
    except (OSError, ValueError, KeyError):
        raise HTTPException(503) from None
    if allowed is not True:
        raise HTTPException(404)
    return row


@router.get('/internal/v1/maintenance-assessment-fee-scope/{request_id}')
async def assessment_fee_scope(request_id: UUID, request_revision: int, buyer_id: UUID, organization_id: UUID, request: Request):
    service(request,{'pricing'})
    async with request.app.state.pool.acquire(timeout=1) as tx:
        row=await tx.fetchrow('''SELECT r.watch_id,r.private_request->>'brand_id' AS brand_id FROM maintenance_requests r
            JOIN maintenance_request_operations o USING(operation_id,actor_id,organization_id)
            WHERE r.id=$1 AND r.actor_id=$2 AND r.organization_id=$3 AND r.revision=$4 AND r.state='submitted'
              AND o.result->>'request_id'=r.id::text AND o.result->>'watch_id'=r.watch_id::text
              AND NOT EXISTS(SELECT 1 FROM maintenance_assessment_decisions d WHERE d.request_id=r.id AND d.state='rejected')''',
            request_id,buyer_id,organization_id,request_revision)
    if row is None:
        raise HTTPException(409)
    try:
        policy=await prerequisite(request,'maintenance_fee_policy',organization_id,UUID(row['brand_id']))
        if (set(policy)!={'organization_id','brand_id','policy_revision','current'} or policy['current'] is not True or
            (UUID(policy['organization_id']),UUID(policy['brand_id']))!=(organization_id,UUID(row['brand_id'])) or
            type(policy['policy_revision']) is not int or policy['policy_revision']<1):
            raise ValueError('assessment_fee_policy_binding')
    except (ValueError, OSError, KeyError, TypeError):
        raise HTTPException(503) from None
    return {'request_id':request_id,'request_revision':request_revision,'buyer_id':buyer_id,'organization_id':organization_id,
        'policy_revision':policy['policy_revision'],'current':True}


async def latest(tx, request_id):
    value = await tx.fetchval('''SELECT receipt FROM maintenance_opening_preferences WHERE request_id=$1
        ORDER BY revision DESC LIMIT 1''',request_id)
    return PreferenceReceipt.model_validate(decoded(value)) if value is not None else None


@router.get('/v1/maintenance/requests/{request_id}/opening-consent', response_model=PreferenceReceipt)
async def current_preference(request_id: UUID, request: Request, buyer=Depends(buyer_identity)):
    async with unit_of_work(request.app.state.pool,lock_key=f'maintenance-staff:{request_id}') as tx:
        await owned(tx,request_id,buyer,request)
        receipt = await latest(tx,request_id)
        if receipt is None:
            raise PublicError('opening_preference_missing','No opening preference has been recorded.',status=404)
        return receipt


@router.get('/v1/maintenance/requests/{request_id}/opening-consent/operations/{operation_id}')
@router.delete('/v1/maintenance/requests/{request_id}/opening-consent/operations/{operation_id}')
async def preference_operation(request_id: UUID, operation_id: UUID, request: Request, buyer=Depends(buyer_identity)):
    async with unit_of_work(request.app.state.pool,lock_key=f'maintenance-staff:{request_id}') as tx:
        await lock_operation(tx,operation_id)
        await owned(tx,request_id,buyer,request)
        saved=await tx.fetchval('SELECT receipt FROM maintenance_opening_preferences WHERE operation_id=$1',operation_id)
        if saved is not None:
            receipt=PreferenceReceipt.model_validate(decoded(saved))
            if (receipt.request_id,receipt.buyer_id)!=(request_id,buyer):
                raise HTTPException(404)
            return receipt
        if request.method!='DELETE':
            raise PublicError('opening_operation_missing','No preference was recorded for this reference.',status=404)
        closed=await tx.fetchrow('''INSERT INTO maintenance_preference_closures VALUES($1,$2,$3)
            ON CONFLICT(operation_id) DO UPDATE SET operation_id=excluded.operation_id
            RETURNING request_id,buyer_id''',operation_id,request_id,buyer)
        if (closed['request_id'],closed['buyer_id'])!=(request_id,buyer):
            raise HTTPException(404)
        return {'state':'closed','request_id':request_id,'buyer_id':buyer,'operation_id':operation_id}


@router.post('/v1/maintenance/requests/{request_id}/opening-consent', response_model=PreferenceReceipt)
async def save_preference(request_id: UUID, body: Preference, request: Request, buyer=Depends(buyer_identity)):
    async with unit_of_work(request.app.state.pool,lock_key=f'maintenance-staff:{request_id}') as tx:
        await lock_operation(tx,body.operation_id)
        row = await owned(tx,request_id,buyer,request)
        saved = await tx.fetchval('SELECT receipt FROM maintenance_opening_preferences WHERE operation_id=$1',body.operation_id)
        if saved is not None:
            old = PreferenceReceipt.model_validate(decoded(saved))
            if (old.request_id,old.buyer_id) != (request_id,buyer):
                raise HTTPException(404)
            if old.model_dump(include=set(Preference.model_fields)) != body.model_dump():
                raise HTTPException(409)
            return old
        if await tx.fetchval('SELECT 1 FROM maintenance_preference_closures WHERE operation_id=$1',body.operation_id):
            raise HTTPException(409)
        await require_request_mutable(tx,request_id)
        case_id = await tx.fetchval('SELECT case_id FROM maintenance_received_cases WHERE request_id=$1',request_id)
        if case_id is not None:
            await lock_case(tx,case_id)
            await require_mutable(tx,case_id)
        current = await latest(tx,request_id)
        if ((current.revision if current else 0) != body.expected_revision or row['revision'] != body.request_revision
                or await tx.fetchval("SELECT 1 FROM maintenance_assessment_decisions WHERE request_id=$1 AND state='rejected'",request_id)):
            raise HTTPException(409)
        receipt=PreferenceReceipt(**body.model_dump(),request_id=request_id,buyer_id=buyer,watch_id=row['watch_id'],
            organization_id=row['organization_id'],revision=body.expected_revision+1,recorded_at=datetime.now(timezone.utc))
        await tx.execute('INSERT INTO maintenance_opening_preferences VALUES($1,$2,$3,$4::jsonb)',
            body.operation_id,request_id,receipt.revision,receipt.model_dump_json())
        return receipt


async def assessment_fee_binding(request, actor, organization, order, receipt):
    try:
        return AssessmentFeeBinding.model_validate(await prerequisite(
            request,'maintenance_assessment_fee_binding',actor,organization,order,receipt))
    except (ValueError,OSError,KeyError):
        raise HTTPException(503) from None


async def assessment_binding(request, actor, organization, order, receipt):
    try:
        custody=await prerequisite(request,'intake_current_custody',actor,organization,order,receipt)
        if custody is False:
            raise HTTPException(409)
        custody=CurrentCustodyReceipt.model_validate(custody)
    except (ValueError,OSError,KeyError):
        raise HTTPException(503) from None
    terms=await assessment_fee_binding(request,actor,organization,order,receipt)
    if (not custody.valid or (custody.actor_id,custody.organization_id,custody.order_id,custody.id)!=
            (actor,organization,order,receipt) or (custody.watch_id,custody.watch_revision,custody.incident_revision)!=
            (custody.current_watch_id,custody.current_watch_revision,custody.current_incident_revision) or
            (terms.organization_id,terms.order_id,terms.receipt_id,terms.watch_id)!=(organization,order,receipt,custody.watch_id)):
        raise HTTPException(409)
    return custody, terms


async def fee_decision(request, terms):
    try:
        fee=AcceptedFee.model_validate(await prerequisite(request,'maintenance_accepted_fee',terms.operation_id,
            terms.request_id,terms.request_revision,terms.buyer_id,terms.organization_id,terms.offer_id,terms.offer_revision))
    except (ValueError,OSError,KeyError):
        raise HTTPException(503) from None
    if any(getattr(fee,key)!=getattr(terms,key) for key in AssessmentFeeBinding.model_fields if key not in ('order_id','watch_id','receipt_id')):
        raise HTTPException(409)
    return fee


async def assessor_scope(tx, organization, actor, *, request_id=None, order_id=None):
    return await tx.fetchrow('''SELECT r.id AS request_id,r.actor_id AS buyer_id,r.watch_id,r.revision,d.order_id,d.custody_receipt_id,
          d.custody_receipt_revision,d.watch_revision,d.incident_revision,a.revision AS assignment_revision
        FROM maintenance_requests r JOIN maintenance_assessment_assignments a ON a.request_id=r.id
        JOIN maintenance_assessment_decisions d ON d.request_id=r.id AND d.assignment_revision=a.revision
        WHERE r.organization_id=$1 AND a.assessor_id=$2 AND a.request_revision=r.revision AND d.state='confirmed'
          AND ($3::uuid IS NULL OR r.id=$3) AND ($4::uuid IS NULL OR d.order_id=$4)''',organization,actor,request_id,order_id)


def check_assessment(row, custody, terms):
    if ((row['request_id'],row['revision'],row['buyer_id'],row['watch_id'],row['order_id'],row['custody_receipt_id'])!=
            (terms.request_id,terms.request_revision,terms.buyer_id,terms.watch_id,terms.order_id,terms.receipt_id) or
            (row['custody_receipt_revision'],row['watch_revision'],row['incident_revision'])!=
            (custody.revision,custody.watch_revision,custody.incident_revision)):
        raise HTTPException(409)


@router.get('/v1/maintenance/opening-consent/intake/{order_id}',response_model=IntakeOpeningReview)
async def intake_review(order_id: UUID, organization_id: UUID, request: Request, actor=Depends(selected)):
    if not (await staff_grant(request,actor,organization_id)).can_assess:
        raise HTTPException(403)
    async with request.app.state.pool.acquire(timeout=1) as tx:
        row=await assessor_scope(tx,organization_id,actor,order_id=order_id)
    if row is None:
        raise PublicError('opening_review_missing','No confirmed maintenance assessment is assigned.',status=404)
    request_id=row['request_id']
    custody,terms=await assessment_binding(request,actor,organization_id,order_id,row['custody_receipt_id'])
    fee=await fee_decision(request,terms)
    async with unit_of_work(request.app.state.pool,lock_key=f'maintenance-staff:{request_id}') as tx:
        if not (await staff_grant(request,actor,organization_id)).can_assess:
            raise HTTPException(403)
        row=await assessor_scope(tx,organization_id,actor,request_id=request_id,order_id=order_id)
        if row is None:
            raise HTTPException(404)
        check_assessment(row,custody,terms)
        preference=await latest(tx,request_id)
        if preference is None or preference.request_revision!=row['revision']:
            raise PublicError('opening_preference_required','The buyer has not recorded current opening preferences.',status=409)
        binding=AcknowledgementBinding(request_revision=row['revision'],consent_revision=preference.revision,
            assignment_revision=row['assignment_revision'],order_id=order_id,receipt_id=custody.id,receipt_revision=custody.revision,
            fee_acceptance_operation_id=fee.operation_id,offer_id=fee.offer_id,offer_revision=fee.offer_revision)
        saved=await tx.fetchval('''SELECT 1 FROM maintenance_opening_acknowledgements WHERE request_id=$1 AND consent_revision=$2''',
            request_id,preference.revision)
        return IntakeOpeningReview(request_id=request_id,organization_id=organization_id,actor_id=actor,watch_id=row['watch_id'],
            received_at=custody.received_at,opening_permitted=preference.opening_permitted,no_polish=preference.no_polish,
            binding=binding,fee=fee,acknowledged=bool(saved))


async def original_acknowledgement(tx, request_id, organization, actor, operation_id):
    saved=await tx.fetchval('SELECT receipt FROM maintenance_opening_acknowledgements WHERE operation_id=$1',operation_id)
    if saved is None:
        return None
    receipt=OpeningAcknowledgement.model_validate(decoded(saved))
    if (receipt.request_id,receipt.actor_id,receipt.organization_id)!=(request_id,actor,organization):
        raise HTTPException(404)
    if await assessor_scope(tx,organization,actor,request_id=request_id) is None:
        raise HTTPException(404)
    return receipt


@router.get('/v1/maintenance/requests/{request_id}/opening-consent/intake/operations/{operation_id}',response_model=OpeningAcknowledgement)
@router.delete('/v1/maintenance/requests/{request_id}/opening-consent/intake/operations/{operation_id}')
async def intake_operation(request_id: UUID, operation_id: UUID, organization_id: UUID, request: Request, actor=Depends(selected)):
    async with unit_of_work(request.app.state.pool,lock_key=f'maintenance-staff:{request_id}') as tx:
        await lock_operation(tx,operation_id)
        if not (await staff_grant(request,actor,organization_id)).can_assess:
            raise HTTPException(403)
        if await assessor_scope(tx,organization_id,actor,request_id=request_id) is None:
            raise HTTPException(404)
        saved=await original_acknowledgement(tx,request_id,organization_id,actor,operation_id)
        if saved is not None:
            return saved
        if request.method!='DELETE':
            raise PublicError('opening_acknowledgement_missing','No acknowledgement was recorded for this reference.',status=404)
        closed=await tx.fetchrow('''INSERT INTO maintenance_acknowledgement_closures VALUES($1,$2,$3,$4)
            ON CONFLICT(operation_id) DO UPDATE SET operation_id=excluded.operation_id
            RETURNING request_id,actor_id,organization_id''',operation_id,request_id,actor,organization_id)
        if (closed['request_id'],closed['actor_id'],closed['organization_id'])!=(request_id,actor,organization_id):
            raise HTTPException(404)
        return {'state':'closed','request_id':request_id,'actor_id':actor,'organization_id':organization_id,'operation_id':operation_id}


async def opening_fence(request, now, deadline, body, custody, terms):
    fence=OpeningFenceRequest(schema_version=1,hold_until=deadline,binding=OpeningFenceBinding(
        operation_id=body.operation_id,assignment_revision=body.assignment_revision,custody=custody,retained_fee=terms))
    raw=fence.model_dump_json().encode('utf-8')
    try:
        result=await prerequisite(request,'maintenance_opening_fence',raw)
        if result is False:
            raise HTTPException(409)
        result=OpeningFenceResult.model_validate(result)
        if (result.binding_hash!=hashlib.sha256(raw).hexdigest() or result.held_until.utcoffset()!=timedelta(0)
                or not deadline<=result.held_until<=now+timedelta(seconds=5)):
            raise ValueError('opening_fence_binding')
    except (ValueError,OSError,KeyError):
        raise HTTPException(503) from None


async def opening_fence_remaining(tx,deadline):
    now=await tx.fetchval('SELECT clock_timestamp()')
    remaining=int((deadline-now-timedelta(seconds=1)).total_seconds()*1000)
    if remaining<=0:
        raise HTTPException(503)
    return remaining


@router.post('/v1/maintenance/requests/{request_id}/opening-consent/intake', response_model=OpeningAcknowledgement)
async def acknowledge(request_id: UUID, organization_id: UUID, body: Acknowledge, request: Request, actor=Depends(selected)):
    if not (await staff_grant(request,actor,organization_id)).can_assess:
        raise HTTPException(403)
    async with unit_of_work(request.app.state.pool,lock_key=f'maintenance-staff:{request_id}') as tx:
        old=await original_acknowledgement(tx,request_id,organization_id,actor,body.operation_id)
        if old is not None:
            if old.model_dump(include=set(Acknowledge.model_fields)) != body.model_dump():
                raise HTTPException(409)
            return old
    # Never hold the local request lock while obtaining Orders authority.
    custody,terms=await assessment_binding(request,actor,organization_id,body.order_id,body.receipt_id)
    fee=await fee_decision(request,terms)
    if (fee.operation_id,fee.offer_id,fee.offer_revision)!=(body.fee_acceptance_operation_id,body.offer_id,body.offer_revision):
        raise HTTPException(409)
    async with request.app.state.pool.acquire(timeout=1) as clock:
        now=await clock.fetchval('SELECT clock_timestamp()')
    deadline=now+timedelta(seconds=4)
    # Refresh assignment coverage through this cutoff without changing the checked terms or extending the window.
    refreshed=await assessment_fee_binding(request,actor,organization_id,body.order_id,body.receipt_id)
    if refreshed!=terms:
        raise HTTPException(409)
    await opening_fence(request,now,deadline,body,custody,terms)
    async with unit_of_work(request.app.state.pool,lock_key=f'maintenance-staff:{request_id}') as tx:
        await lock_operation(tx,body.operation_id)
        if not (await staff_grant(request,actor,organization_id)).can_assess:
            raise HTTPException(403)
        row=await assessor_scope(tx,organization_id,actor,request_id=request_id,order_id=body.order_id)
        if not row:
            raise HTTPException(404)
        old=await original_acknowledgement(tx,request_id,organization_id,actor,body.operation_id)
        if old is not None:
            if old.model_dump(include=set(Acknowledge.model_fields)) != body.model_dump():
                raise HTTPException(409)
            return old
        if await tx.fetchval('SELECT 1 FROM maintenance_acknowledgement_closures WHERE operation_id=$1',body.operation_id):
            raise HTTPException(409)
        # The fee read leases the assignment. Appending its exact acknowledgement
        # leaves the covered request, assignment, confirmation and preference unchanged.
        check_assessment(row,custody,terms)
        case_id=await tx.fetchval('SELECT case_id FROM maintenance_received_cases WHERE request_id=$1',request_id)
        if case_id is not None:
            await lock_case(tx,case_id)
            await require_mutable(tx,case_id)
        preference=await latest(tx,request_id)
        if (preference is None or preference.revision!=body.consent_revision or preference.request_revision!=body.request_revision
                or (row['revision'],row['assignment_revision'],row['order_id'],row['custody_receipt_id'],row['custody_receipt_revision'])
                != (body.request_revision,body.assignment_revision,body.order_id,body.receipt_id,body.receipt_revision)):
            raise HTTPException(409)
        result=OpeningAcknowledgement(**body.model_dump(),request_id=request_id,actor_id=actor,buyer_id=row['buyer_id'],
            organization_id=organization_id,watch_id=row['watch_id'],watch_revision=row['watch_revision'],
            incident_revision=row['incident_revision'],customer_opening_permission=preference.opening_permitted,
            customer_no_polish_acknowledged=True,no_polish=preference.no_polish,accepted_assessment_fee=True,
            accepted_fee_minor=fee.amount_minor,policy_revision=fee.policy_revision,received_at=custody.received_at)
        remaining=await opening_fence_remaining(tx,deadline)
        # A stalled transaction must roll back before the Orders lease can expire.
        await tx.execute("SELECT set_config('transaction_timeout', $1, true)",f'{min(remaining,2000)}ms')
        inserted=await tx.fetchval('''INSERT INTO maintenance_opening_acknowledgements VALUES($1,$2,$3,$4::jsonb)
            ON CONFLICT (request_id,consent_revision) DO NOTHING RETURNING operation_id''',
            body.operation_id,request_id,body.consent_revision,result.model_dump_json())
        if inserted is None:
            raise HTTPException(409)
        await opening_fence_remaining(tx,deadline)
        return result


@router.get('/internal/v1/maintenance/requests/{request_id}/opening-consent',response_model=OpeningAcknowledgement)
async def current_acknowledgement(request_id: UUID, actor_id: UUID, organization_id: UUID, order_id: UUID, receipt_id: UUID,
                                 request: Request):
    service(request,{'orders'})
    # Orders owns the physical receipt independently and may hold its own transaction here.
    async with unit_of_work(request.app.state.pool) as tx:
        if not await tx.fetchval('SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))',f'maintenance-staff:{request_id}'):
            raise HTTPException(503)
        return await acknowledged(tx,request_id,actor_id,organization_id,order_id,receipt_id)


async def acknowledged(tx, request_id, actor, organization, order, receipt):
    value=await tx.fetchval('''SELECT a.receipt FROM maintenance_opening_acknowledgements a
        JOIN maintenance_requests r ON r.id=a.request_id AND r.organization_id=$3
        JOIN maintenance_assessment_assignments s ON s.request_id=r.id AND s.assessor_id=$2 AND s.request_revision=r.revision
        JOIN maintenance_assessment_decisions d ON d.request_id=r.id AND d.assignment_revision=s.revision
             AND d.state='confirmed' AND d.order_id=$4 AND d.custody_receipt_id=$5
        WHERE a.request_id=$1 AND a.receipt @> jsonb_build_object('actor_id',s.assessor_id,
          'assignment_revision',s.revision,'order_id',d.order_id,'receipt_id',d.custody_receipt_id,
          'receipt_revision',d.custody_receipt_revision,'incident_revision',d.incident_revision)
          AND a.consent_revision=(SELECT max(revision) FROM maintenance_opening_preferences WHERE request_id=r.id)
        ORDER BY a.operation_id LIMIT 1''',request_id,actor,organization,order,receipt)
    if value is None:
        raise HTTPException(409)
    try:
        return OpeningAcknowledgement.model_validate(decoded(value))
    except ValueError:
        raise HTTPException(503) from None
