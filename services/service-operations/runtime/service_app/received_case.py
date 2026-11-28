"""Private links from acknowledged maintenance requests to physical intake."""
from fastapi import HTTPException

from bt_contracts.service.maintenance.diagnosis import CaseRequestBinding
from .sources import current_commitment, require_assessment_fee_commitment


async def submitted_request(tx, request_id, organization, watch, *, lock=True):
    query = """
        SELECT r.id, r.actor_id, r.revision,
               (r.private_request->>'watch_revision')::numeric AS watch_revision
        FROM maintenance_requests r
        JOIN maintenance_request_operations o ON o.operation_id=r.operation_id
            AND o.actor_id=r.actor_id AND o.organization_id=r.organization_id
        WHERE r.id=$1 AND r.organization_id=$2 AND r.watch_id=$3 AND r.state='submitted'
          AND jsonb_typeof(r.private_request->'watch_revision')='number'
          AND o.result @> jsonb_build_object(
              'state', 'submitted', 'request_id', r.id, 'watch_id', r.watch_id,
              'operation_id', r.operation_id, 'actor_id', r.actor_id,
              'subject_id', r.actor_id, 'organization_id', r.organization_id,
              'revision', r.revision, 'watch_revision', r.private_request->'watch_revision')
        """
    if lock:
        query += ' FOR SHARE OF r, o'
    return await tx.fetchrow(query, request_id, organization, watch)


async def retained_scope_submission(tx, case_id, *, lock=True):
    """Verify the local submission and exact confirmed intake after payment moves on."""
    if not await tx.fetchval("SELECT to_regclass('public.maintenance_assessment_decisions') IS NOT NULL"):
        return False
    query = """
        SELECT b.request_id, d.organization_id, d.watch_id, s.buyer_id,
               s.body->>'request_revision' AS scope_request_revision
        FROM maintenance_received_cases b
        JOIN service_diagnoses d ON d.case_id=b.case_id AND d.request_id=b.request_id
            AND d.body->>'case_id'=b.case_id::text
            AND d.body->>'request_id'=b.request_id::text
            AND d.body->>'watch_id'=d.watch_id::text
            AND d.body->>'fee_quote_id'=b.fee_quote_id::text
            AND d.body->'fee_quote_revision'=to_jsonb(b.fee_quote_revision)
        JOIN service_case_scopes s ON s.case_id=b.case_id AND s.request_id=b.request_id
            AND s.organization_id=d.organization_id AND d.body->>'buyer_id'=s.buyer_id::text
        JOIN maintenance_assessment_decisions c ON c.request_id=d.request_id AND c.state='confirmed'
            AND c.organization_id=d.organization_id AND c.watch_id=d.watch_id
            AND c.order_id::text=d.body->>'order_id' AND c.custody_receipt_id::text=d.body->>'receipt_id'
            AND to_jsonb(c.custody_receipt_revision)=d.body->'receipt_revision'
            AND to_jsonb(c.incident_revision)=d.body->'incident_revision'
            AND to_jsonb(c.watch_revision)=d.body->'watch_revision'
        WHERE b.case_id=$1
        """
    if lock:
        query += ' FOR SHARE OF b,c'
    row = await tx.fetchrow(query, case_id)
    if not row:
        return False
    submission = await submitted_request(
        tx, row['request_id'], row['organization_id'], row['watch_id'], lock=lock)
    return bool(submission and submission['actor_id'] == row['buyer_id']
                and row['scope_request_revision'] in (None, str(submission['revision'])))


async def verify_submission(request, tx, opening, request_id, *, commitment=None):
    source = await submitted_request(tx, request_id, opening.organization_id, opening.watch_id)
    if not source:
        raise HTTPException(409)
    if commitment is None:
        try:
            commitment = await current_commitment(request, opening.order_id)
        except (ConnectionError, TimeoutError):
            raise HTTPException(503) from None
    require_assessment_fee_commitment(commitment, opening, source['actor_id'])
    reservation_input = opening.reservation_input_watch_revision
    if (reservation_input is None or source['watch_revision'] != reservation_input
            or reservation_input + 1 != commitment.watch_revision):
        raise HTTPException(409)
    return source


async def case_binding(request, tx, case_id, opening, *, commitment=None):
    link = await tx.fetchrow("""
        SELECT request_id, fee_quote_id, fee_quote_revision
        FROM maintenance_received_cases WHERE case_id=$1 FOR SHARE
        """, case_id)
    if (not link or (link['fee_quote_id'], link['fee_quote_revision']) != (
            opening.quote_id, opening.quote_revision)
            or opening.maintenance_request_id != link['request_id']):
        raise HTTPException(409)
    source = await verify_submission(request, tx, opening, link['request_id'], commitment=commitment)
    return CaseRequestBinding(case_id=case_id, request_id=source['id'], watch_id=opening.watch_id,
                              buyer_id=source['actor_id'], order_id=opening.order_id, current=True)
