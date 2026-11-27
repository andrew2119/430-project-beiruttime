"""Request transport. Composition supplies the current-authority provider."""
import asyncio
import base64
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from bt_contracts.service.maintenance.v1 import (
    AssessmentAccess, AssessmentPhoto, AssessmentQueue, AssessmentQueueAccess,
    AssessmentRequest, Context, DeliveryHold, DeliveryRecoveryCommand, Photo, PhotoBinding, PhotoReceipt, Result,
    Request as MaintenanceRequest,
)
from bt_runtime.app.db import unit_of_work
from bt_contracts_core.errors import PublicError
from .commands import submit, lookup, Rejected
from .delivery import escalate_due, fence_operator
from .photos import discard_unattached, operation_lock, store_photo
from .provider import Provider, buyer_identity, identity as current_identity

router = APIRouter(prefix='/v1/maintenance', tags=['maintenance requests'])

async def identity(request: Request):
    resolver = getattr(request.app.state, 'maintenance_identity', None)
    if resolver is None:
        resolver = buyer_identity
    try:
        return await asyncio.wait_for(resolver(request), timeout=1.2)
    except (TimeoutError, ConnectionError):
        raise HTTPException(503) from None

def authority_provider(request):
    return getattr(request.app.state, 'maintenance_provider', None) or Provider(request)


async def staff_identity(request: Request, organization_id: UUID):
    if len(request.query_params.getlist('organization_id')) != 1:
        raise HTTPException(422)
    actor = await current_identity(request, organization_id)
    return actor.actor.subject_id


@router.post('/requests', response_model=Result, status_code=201)
async def create(body: MaintenanceRequest, request: Request, actor_id=Depends(identity)):
    provider = authority_provider(request)
    def transaction(operation_id):
        return unit_of_work(request.app.state.pool, lock_key=operation_lock(operation_id))
    try:
        return await submit(body, actor_id=actor_id, provider=provider, transaction=transaction)
    except Rejected as error:
        code = str(error)
        if code == 'destination_ineligible':
            raise PublicError(code, 'Review the currently eligible businesses and assessments.', status=409) from None
        if code == 'photo_unavailable':
            raise PublicError(code, 'Prepare the private photos again before retrying.', status=409) from None
        if code == 'watch_committed':
            raise PublicError(code, 'This watch already has a sale or service commitment.', status=409) from None
        raise HTTPException({'denied':403,'stale':409,'operation_conflict':409,
            'assessment_permission_required':422,'pending':503}.get(code,503), detail=code) from None

@router.delete('/operations/{operation_id}')
async def close_operation(operation_id: UUID, organization_id: UUID, request: Request, actor_id=Depends(identity)):
    return await resolve_operation(operation_id, organization_id, request, actor_id, close=True)


@router.get('/operations/{operation_id}', response_model=Result)
async def operation(operation_id: UUID, organization_id: UUID, request: Request, actor_id=Depends(identity)):
    return await resolve_operation(operation_id, organization_id, request, actor_id)


async def resolve_operation(operation_id, organization_id, request, actor_id, *, close=False):
    provider = authority_provider(request)
    check = getattr(provider, 'operation_access', None)
    if not callable(check):
        raise HTTPException(503)
    async with unit_of_work(request.app.state.pool, lock_key=operation_lock(operation_id)) as tx:
        result = await lookup(operation_id, actor_id=actor_id, organization_id=organization_id,
                              current_permission=True, tx=tx)
        extra = ()
        if isinstance(provider, Provider) and result is not None:
            extra = (UUID(result['watch_id']), result['intervention'], UUID(result['brand_id']))
        try:
            allowed = await asyncio.wait_for(check(actor_id, organization_id, operation_id, *extra), timeout=1.2)
        except (TimeoutError, ConnectionError, ValueError, KeyError):
            raise HTTPException(503) from None
        if allowed is False:
            raise HTTPException(403)
        if allowed is not True:
            raise HTTPException(503)
        if result is None and close:
            await tx.execute('''INSERT INTO maintenance_closed_operations
                (operation_id, actor_id, organization_id) VALUES ($1,$2,$3)
                ON CONFLICT DO NOTHING''', operation_id, actor_id, organization_id)
            await discard_unattached(tx, operation_id, actor_id, organization_id)
            return {'closed': True, 'operation_id': operation_id, 'organization_id': organization_id}
    if result is None:
        raise PublicError('operation_missing', 'No maintenance receipt is available for this operation.', status=404)
    return result

@router.get('/context/{watch_id}', response_model=Context)
async def context(watch_id: UUID, request: Request, actor_id=Depends(identity), brand_id: UUID | None = None):
    provider = authority_provider(request)
    try:
        read = provider.context(actor_id, watch_id, brand_id) if isinstance(provider, Provider) else provider.context(actor_id, watch_id)
        value = Context.model_validate(await asyncio.wait_for(read, timeout=1.2))
    except (TimeoutError, ConnectionError, ValueError):
        raise HTTPException(503) from None
    if value.actor_id != actor_id or value.subject_id != actor_id or value.watch_id != watch_id:
        raise HTTPException(403)
    return value

@router.post('/photos', response_model=PhotoReceipt)
async def photo(body: Photo, request: Request, actor_id=Depends(identity)):
    if not body.safe_photo_declared:
        raise HTTPException(422)
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except ValueError:
        raise HTTPException(422) from None
    signatures = {'image/jpeg': content.startswith(b'\xff\xd8\xff'),
        'image/png': content.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/webp': content.startswith(b'RIFF') and content[8:12] == b'WEBP'}
    if not 1 <= len(content) <= 262144 or not signatures[body.media_type]:
        raise HTTPException(422)
    async with unit_of_work(request.app.state.pool, lock_key=operation_lock(body.request_operation_id)) as tx:
        current = await context(body.watch_id, request, actor_id, body.brand_id)
        destination = next((item for item in current.destinations
                            if item.organization_id == body.organization_id
                            and item.brand_id == body.brand_id
                            and body.intervention in item.interventions), None)
        if destination is None:
            raise PublicError('destination_ineligible',
                              'Review the currently eligible businesses and assessments.', status=409)
        if (current.watch_revision, destination.capability_revision, destination.policy_revision) != (
            body.watch_revision, body.capability_revision, body.policy_revision
        ):
            raise PublicError('stale_photo_scope', 'Review the current assessment before attaching photos.', status=409)
        reference = await store_photo(tx, actor_id, body, content)
    return PhotoReceipt(**body.model_dump(include=set(PhotoBinding.model_fields)),
                        actor_id=actor_id, subject_id=current.subject_id, photo_ref=reference, revision=1)


@router.get('/assessment-inbox', response_model=AssessmentQueue)
async def assessment_inbox(organization_id: UUID, request: Request,
                           offset: Annotated[int, Query(ge=0, le=10000)] = 0, actor_id=Depends(staff_identity)):
    provider = authority_provider(request)
    check = getattr(provider, 'assessment_queue_access', None)
    if not callable(check):
        raise HTTPException(503)
    try:
        value = await asyncio.wait_for(check(actor_id, organization_id), timeout=1.2)
        if value is False:
            raise HTTPException(403)
        access = AssessmentQueueAccess.model_validate(value)
    except (OSError, ValueError):
        raise HTTPException(503) from None
    if (access.actor_id, access.organization_id) != (actor_id, organization_id):
        raise HTTPException(403)
    async with request.app.state.pool.acquire(timeout=2) as tx:
        page = await tx.fetchrow("""
            WITH current_inbox AS (
                SELECT i.request_id, i.delivered_at FROM maintenance_assessment_inbox i
                LEFT JOIN maintenance_assessment_decisions d ON d.request_id=i.request_id
                WHERE i.organization_id=$1 AND ($4::boolean OR (i.request_id=ANY($2::uuid[]) AND
                    (NOT $6::boolean OR EXISTS (SELECT 1 FROM maintenance_assessment_assignments a
                      JOIN maintenance_requests r ON r.id=a.request_id AND r.revision=a.request_revision
                      WHERE a.request_id=i.request_id AND a.organization_id=i.organization_id AND a.assessor_id=$5))))
                  AND d.state IS DISTINCT FROM 'rejected'
            )
            SELECT (SELECT count(*) FROM current_inbox) AS total,
                   ARRAY(SELECT request_id FROM current_inbox
                         ORDER BY delivered_at DESC, request_id LIMIT 50 OFFSET $3) AS ids,
                   ARRAY(SELECT delivered_at FROM current_inbox
                         ORDER BY delivered_at DESC, request_id LIMIT 50 OFFSET $3) AS times
        """, organization_id, access.request_ids, offset, access.routing_allowed, actor_id, isinstance(provider, Provider))
    total = page['total']
    items = [{'request_id': request_id, 'delivered_at': delivered_at}
             for request_id, delivered_at in zip(page['ids'], page['times'], strict=True)]
    return AssessmentQueue(items=items, total=total, next_offset=offset + 50 if offset + 50 < total else None)


async def assigned_request(request, actor_id, organization_id, request_id, tx):
    provider = authority_provider(request)
    check = getattr(provider, 'assessment_access', None)
    if not callable(check):
        raise HTTPException(503)
    try:
        call = check(actor_id, organization_id, request_id, tx) if isinstance(provider, Provider) else check(actor_id, organization_id, request_id)
        value = await asyncio.wait_for(call, timeout=1.2)
    except HTTPException as error:
        if error.status_code == 401:
            raise
        if error.status_code in (403, 404):
            raise HTTPException(404) from None
        raise HTTPException(503) from None
    except (OSError, ValueError):
        raise HTTPException(503) from None
    if value is False:
        raise HTTPException(404)
    try:
        access = AssessmentAccess.model_validate(value)
    except ValueError:
        raise HTTPException(503) from None
    if not access.allowed or (access.actor_id, access.organization_id, access.request_id) != (
        actor_id, organization_id, request_id
    ):
        raise HTTPException(404)
    row = await tx.fetchrow(
        '''SELECT private_request, revision, submitted_at FROM maintenance_requests
           WHERE id=$1 AND organization_id=$2 FOR SHARE''', request_id, organization_id)
    if row is None:
        raise HTTPException(404)
    saved = MaintenanceRequest.model_validate_json(row['private_request'])
    if (access.watch_id, access.brand_id, access.intervention, access.request_revision) != (
        saved.watch_id, saved.brand_id, saved.intervention, row['revision']
    ):
        raise HTTPException(404)
    if not saved.limited_assessment_permission:
        raise HTTPException(404)
    return saved, row, access


@router.get('/requests/{request_id}', response_model=AssessmentRequest)
async def assessment(request_id: UUID, organization_id: UUID, request: Request,
                     actor_id=Depends(staff_identity)):
    async with unit_of_work(request.app.state.pool, lock_key=f'maintenance-staff:{request_id}') as tx:
        saved, row, access = await assigned_request(request, actor_id, organization_id, request_id, tx)
    return AssessmentRequest(
        request_id=request_id, revision=row['revision'], submitted_at=row['submitted_at'],
        assessor_id=access.actor_id, assignment_revision=access.assignment_revision,
        watch_id=saved.watch_id, brand_id=saved.brand_id, intervention=saved.intervention,
        reported_symptoms=saved.reported_symptoms, known_modifications=saved.known_modifications,
        limited_assessment_permission=True, photo_refs=saved.photo_refs)


@router.get('/requests/{request_id}/photos/{photo_ref}', response_model=AssessmentPhoto)
async def assessment_photo(request_id: UUID, photo_ref: UUID, organization_id: UUID,
                           request: Request, actor_id=Depends(staff_identity)):
    async with unit_of_work(request.app.state.pool, lock_key=f'maintenance-staff:{request_id}') as tx:
        saved, _, _ = await assigned_request(request, actor_id, organization_id, request_id, tx)
        if photo_ref not in saved.photo_refs:
            raise HTTPException(404)
        row = await tx.fetchrow(
            '''SELECT media_type, content FROM maintenance_request_photos
               WHERE photo_ref=$1 AND request_id=$2 AND request_operation_id=$3
               AND organization_id=$4 AND actor_id=$5 AND watch_id=$6''',
            photo_ref, request_id, saved.operation_id, organization_id, saved.actor_id, saved.watch_id)
    if row is None:
        raise HTTPException(503)
    return AssessmentPhoto(photo_ref=photo_ref, media_type=row['media_type'],
                           content_base64=base64.b64encode(row['content']).decode('ascii'))


async def require_delivery_recovery(request, actor_id, tx):
    state = request.app.state
    if actor_id != getattr(state, 'maintenance_delivery_operator_id', None):
        raise HTTPException(403)
    check = getattr(authority_provider(request), 'delivery_authority_until', None)
    if not callable(check):
        raise HTTPException(503)
    try:
        until = await asyncio.wait_for(check(actor_id), timeout=1.2)
        if until is None:
            raise HTTPException(403)
        await fence_operator(tx, until)
    except (OSError, ValueError, TypeError):
        raise HTTPException(503) from None


async def recovery_identity(request: Request):
    actor = await current_identity(request)
    if actor.actor.organization_id is not None:
        raise HTTPException(403)
    return actor.actor.subject_id


@router.get('/delivery-recovery', response_model=list[DeliveryHold])
async def held_deliveries(request: Request, actor_id=Depends(recovery_identity),
                          offset: Annotated[int, Query(ge=0)] = 0):
    async with unit_of_work(request.app.state.pool) as tx:
        await require_delivery_recovery(request, actor_id, tx)
        rows = await tx.fetch("""
            SELECT o.event_id AS operation_id, $1::uuid AS operator_id,
                   COALESCE(o.held_at, o.last_requeued_hold_at) AS held_at,
                   COALESCE(o.held_at, o.last_requeued_hold_at) + interval '24 hours' AS next_review_at,
                   o.escalation_started_at + interval '48 hours' AS escalate_at, o.escalated_at,
                   o.held_at IS NULL AND o.delivered_at IS NULL AS retry_in_progress,
                   e.reviewed_at AS escalation_reviewed_at,
                   r.responded_at AS first_response_at,
                   COALESCE(r.responded_at, statement_timestamp()) >=
                       COALESCE(o.held_at, o.last_requeued_hold_at) + interval '24 hours'
                       AS first_response_overdue,
                   CASE WHEN o.delivered_at IS NOT NULL THEN 'review_delivered_escalation'
                        WHEN o.held_at IS NULL AND e.reviewed_at IS NULL THEN 'review_active_escalation'
                        WHEN o.held_at IS NULL THEN 'monitor_escalated_retry'
                        WHEN o.escalated_at IS NOT NULL THEN 'resolve_escalated_delivery'
                        WHEN r.responded_at IS NULL AND statement_timestamp() >= o.held_at + interval '24 hours'
                        THEN 'respond_to_overdue_delivery'
                        ELSE 'review_and_retry_delivery' END AS next_action
            FROM maintenance_request_outbox o
            LEFT JOIN maintenance_delivery_responses r ON r.event_id = o.event_id
                AND r.held_at = COALESCE(o.held_at, o.last_requeued_hold_at)
            LEFT JOIN maintenance_delivery_escalations e ON e.event_id = o.event_id
                AND e.held_at = o.escalation_started_at
            WHERE (o.delivered_at IS NULL
                   AND ((o.operator_id = $1 AND o.held_at IS NOT NULL)
                        OR (o.held_at IS NULL AND e.event_id IS NOT NULL)))
                OR (o.delivered_at IS NOT NULL AND e.event_id IS NOT NULL AND e.reviewed_at IS NULL)
            ORDER BY (o.escalated_at IS NULL), (r.responded_at IS NOT NULL),
                COALESCE(o.held_at, o.last_requeued_hold_at), o.event_id LIMIT 50 OFFSET $2
        """, actor_id, offset)
    return [DeliveryHold(**row) for row in rows]


@router.post('/delivery-recovery/{operation_id}', status_code=204)
async def retry_delivery(operation_id: UUID, body: DeliveryRecoveryCommand, request: Request,
                         actor_id=Depends(recovery_identity)):
    async with unit_of_work(request.app.state.pool, lock_key=operation_lock(operation_id)) as tx:
        await require_delivery_recovery(request, actor_id, tx)
        if body.action == 'retry' and await tx.fetchval("""
            SELECT true FROM maintenance_delivery_retry_receipts
            WHERE event_id = $1 AND operator_id = $2 AND held_at = $3
        """, operation_id, actor_id, body.held_at):
            return
        if body.action == 'review_escalation':
            # Serialize with worker transitions. A durable review can replay
            # after delivery or another hold, under current operator access.
            delivery = await tx.fetchrow("""
                SELECT held_at, last_requeued_hold_at, escalation_started_at
                FROM maintenance_request_outbox WHERE event_id = $1 FOR UPDATE
            """, operation_id)
            if await tx.fetchval("""
                SELECT true FROM maintenance_delivery_escalations
                WHERE event_id = $1 AND reviewed_hold_at = $2 AND reviewed_by = $3
            """, operation_id, body.held_at, actor_id):
                return
            if (delivery and delivery['held_at'] is None
                    and delivery['last_requeued_hold_at'] == body.held_at):
                recorded_review = await tx.fetchval("""
                    UPDATE maintenance_delivery_escalations
                    SET reviewed_at = clock_timestamp(), reviewed_by = $3, reviewed_hold_at = $4
                    WHERE event_id = $1 AND held_at = $2 AND reviewed_at IS NULL
                    RETURNING event_id
                """, operation_id, delivery['escalation_started_at'], actor_id, body.held_at)
                if recorded_review is not None:
                    return
            raise PublicError('delivery_hold_changed', 'Refresh the current delivery hold.', status=409)
        recorded = await tx.fetchval("""
            SELECT event_id FROM maintenance_request_outbox
            WHERE event_id = $1 AND operator_id = $2 AND held_at = $3 FOR UPDATE
        """, operation_id, actor_id, body.held_at)
        if recorded is not None:
            await tx.execute("""
                INSERT INTO maintenance_delivery_responses (event_id, held_at, operator_id, responded_at)
                VALUES ($1, $2, $3, clock_timestamp())
                ON CONFLICT (event_id, held_at) DO NOTHING
            """, operation_id, body.held_at, actor_id)
        if body.action == 'acknowledge':
            if recorded is not None or await tx.fetchval("""
                SELECT true FROM maintenance_delivery_responses
                WHERE event_id = $1 AND operator_id = $2 AND held_at = $3
            """, operation_id, actor_id, body.held_at):
                return
            raise PublicError('delivery_hold_changed', 'Refresh the current delivery hold.', status=409)
        if recorded is not None:
            await escalate_due(tx, actor_id, event_id=recorded)
        result = await tx.fetchval("""
            UPDATE maintenance_request_outbox
            SET attempts = 0, next_attempt_at = statement_timestamp(), held_at = NULL, operator_id = NULL,
                last_requeued_hold_at = held_at, last_requeued_by = operator_id
            WHERE event_id = $1 AND operator_id = $2 AND held_at = $3
            RETURNING event_id
        """, operation_id, actor_id, body.held_at)
        if result is None:
            raise PublicError('delivery_hold_changed', 'Refresh the current delivery hold.', status=409)
        await tx.execute("""
            INSERT INTO maintenance_delivery_retry_receipts (event_id, operator_id, held_at)
            VALUES ($1, $2, $3)
        """, operation_id, actor_id, body.held_at)
