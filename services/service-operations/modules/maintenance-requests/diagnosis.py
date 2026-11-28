"""Received-case diagnosis commands, immutable receipts and current source DTO."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_contracts.service.maintenance.diagnosis import Diagnose, DiagnosisAuthorization
from bt_contracts.service.intake.current import OpeningAuthority, RecordAccess
from starlette.responses import Response
from bt_runtime.app.db import unit_of_work
from service_app.received_case import case_binding
from service_app.sources import official_business, principal, service, prerequisite

router = APIRouter()
FENCE_TIMEOUT_SECONDS = 8


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


async def authority(request, actor, organization, intake, watch, assignment=None):
    try:
        facts = OpeningAuthority.model_validate(await prerequisite(request, 'intake_opening_authority', actor, organization, intake["order_id"]))
        access = RecordAccess.model_validate(await prerequisite(request, 'intake_record_access', actor, organization, intake["order_id"], 'write'))
    except (ConnectionError, ValueError, TimeoutError):
        raise HTTPException(503) from None
    private = decoded(intake['private_record'])
    if ((access.actor_id, access.organization_id, access.order_id, access.permission, access.allowed) !=
            (actor, organization, intake['order_id'], 'write', True) or assignment is not None and access.assignment_revision != assignment):
        raise HTTPException(403)
    if (intake['state'] != 'received' or facts.actor_id != actor or facts.organization_id != organization
            or facts.order_id != intake['order_id'] or facts.watch_id != watch
            or facts.receipt_id != intake['custody_receipt_id'] or facts.receipt_revision != intake['custody_revision']
            or facts.received_at != intake['received_at'] or facts.received_at > datetime.now(timezone.utc)
            or not all((facts.current, facts.assigned, facts.permission, facts.customer_opening_permission,
                        facts.accepted_assessment_fee, facts.customer_no_polish_acknowledged,
                        private['diagnostic_opening_permission'], private['fee_acknowledged'], private['no_polish_acknowledged']))
            or private['currency'] != 'USD' or private['fee_minor'] != facts.accepted_fee_minor):
        raise HTTPException(409)
    try:
        await official_business(request, organization, 'servicing')
    except (ConnectionError, TimeoutError):
        raise HTTPException(503) from None
    return facts


def acknowledgement(receipt):
    # Older acknowledgements may contain the admission-time permission flags.
    historical = {key: value for key, value in decoded(receipt).items()
                  if key not in ('current', 'diagnosis_allowed')}
    return {**historical, 'state': 'assessed'}


@router.post('/internal/v1/service-cases/{case_id}/diagnosis')
@router.post('/v1/service-cases/{case_id}/diagnosis')
async def diagnose(case_id: UUID, body: Diagnose, request: Request, actor=Depends(principal)):
    if (body.actor_id, body.organization_id, body.case_id) != (actor.actor.subject_id, actor.actor.organization_id, case_id):
        raise HTTPException(403)
    async with unit_of_work(request.app.state.pool, lock_key=f'diagnosis:{case_id}') as tx:
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', str(body.operation_id))
        intake = await tx.fetchrow('SELECT * FROM technical_intakes WHERE id=$1 AND organization_id=$2 FOR SHARE', case_id, body.organization_id)
        if not intake:
            raise HTTPException(409)
        facts = await authority(request, body.actor_id, body.organization_id, intake, body.watch_id, body.assignment_revision)
        binding = await case_binding(request, tx, case_id, facts)
        if binding.request_id != body.request_id:
            raise HTTPException(409)
        prior = await tx.fetchrow('SELECT command,receipt FROM service_diagnosis_operations WHERE operation_id=$1', body.operation_id)
        if prior:
            if decoded(prior['command']) != body.model_dump(mode='json'):
                raise HTTPException(409)
            return acknowledgement(prior['receipt'])
        retained = await tx.fetchrow('SELECT * FROM service_diagnoses WHERE case_id=$1 FOR UPDATE', case_id)
        if retained and (retained['request_id'],retained['watch_id'],retained['organization_id']) != (body.request_id,body.watch_id,body.organization_id):
            raise HTTPException(409)
        revision = retained['revision'] if retained else 0
        if revision != body.expected_revision:
            raise HTTPException(409)
        assessment = uuid4()
        receipt = {**body.model_dump(mode='json'), 'id': str(assessment), 'revision': revision+1,
            'case_revision': revision+1, 'assessment_id': str(assessment), 'assessment_revision': revision+1,
            'buyer_id': str(binding.buyer_id), 'status': 'diagnosed', 'currency': 'USD',
            'line_ids': [str(line.id) for line in body.lines],
            'order_id': str(intake['order_id']), 'receipt_id': str(facts.receipt_id),
            'receipt_revision': facts.receipt_revision, 'watch_revision': facts.watch_revision,
            'fee_quote_id': str(facts.quote_id), 'fee_quote_revision': facts.quote_revision,
            'intake_revision': intake['revision'], 'intake_received_at': intake['received_at'].isoformat(),
            'consent_revision': facts.consent_revision, 'incident_revision': facts.incident_revision,
            'accepted_terms_revision': facts.accepted_terms_revision, 'recorded_at': datetime.now(timezone.utc).isoformat()}
        encoded = json.dumps(receipt)
        await tx.execute('''INSERT INTO service_diagnoses VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)
            ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,assessment_id=excluded.assessment_id,body=excluded.body''',
            case_id, body.request_id, body.organization_id, body.watch_id, revision+1, assessment, encoded)
        await tx.execute('INSERT INTO service_diagnosis_operations VALUES($1,$2,$3,$4::jsonb,$5::jsonb)', body.operation_id, body.actor_id, body.organization_id, body.model_dump_json(), encoded)
        await tx.execute('INSERT INTO service_diagnosis_outbox(operation_id,case_id,revision) VALUES($1,$2,$3)', body.operation_id, case_id, revision+1)
        return acknowledgement(receipt)


@router.get('/internal/v1/service-cases/{case_id}/diagnosis/operations/{operation_id}')
async def operation(case_id: UUID, operation_id: UUID, request: Request, actor=Depends(principal)):
    organization = actor.actor.organization_id
    person = actor.actor.subject_id
    async with request.app.state.pool.acquire() as tx:
        receipt = await tx.fetchval(
            """SELECT receipt FROM service_diagnosis_operations
               WHERE operation_id=$1 AND actor_id=$2 AND organization_id=$3
                 AND command->>'case_id'=$4""", operation_id, person, organization, str(case_id))
    if receipt is None:
        raise HTTPException(404)
    order = UUID(decoded(receipt)['order_id'])
    try:
        access = RecordAccess.model_validate(await prerequisite(
            request, 'intake_record_access', person, organization, order, 'write'))
    except (ConnectionError, ValueError, TimeoutError):
        raise HTTPException(503) from None
    if (access.actor_id, access.organization_id, access.order_id, access.permission, access.allowed) != (
            person, organization, order, 'write', True):
        raise HTTPException(403)
    return acknowledgement(receipt)


@router.get('/internal/v1/service-cases/{case_id}/diagnosis')
async def current(case_id: UUID, request: Request):
    service(request, {'pricing', 'orders'})
    async with unit_of_work(request.app.state.pool) as tx:
        return await current_diagnosis(request, tx, case_id)


async def current_diagnosis(request, tx, case_id, *, fence=False):
    lock = ' FOR SHARE' if fence else ''
    intake = await tx.fetchrow('SELECT * FROM technical_intakes WHERE id=$1' + lock, case_id)
    row = await tx.fetchrow('SELECT body FROM service_diagnoses WHERE case_id=$1' + lock, case_id)
    if not row or not intake:
        raise HTTPException(404)
    saved = decoded(row['body'])
    facts = await authority(request, UUID(saved['actor_id']), UUID(saved['organization_id']), intake, UUID(saved['watch_id']), saved['assignment_revision'])
    if (facts.watch_revision,facts.consent_revision,facts.accepted_terms_revision,intake['revision']) != (saved['watch_revision'],saved['consent_revision'],saved['accepted_terms_revision'],saved['intake_revision']):
        raise HTTPException(409)
    if (saved.get('fee_quote_id'), saved.get('fee_quote_revision'), saved.get('incident_revision')) != (
            str(facts.quote_id), facts.quote_revision, facts.incident_revision):
        raise HTTPException(409)
    if (saved['receipt_id'], saved['receipt_revision']) != (
            str(facts.receipt_id), facts.receipt_revision):
        raise HTTPException(409)
    binding = await case_binding(request, tx, case_id, facts)
    if any(str(getattr(binding, key)) != saved[key] for key in
           ('case_id', 'request_id', 'watch_id', 'buyer_id', 'order_id')):
        raise HTTPException(409)
    still_current = await tx.fetchval(
        """SELECT 1 FROM service_diagnoses d
               JOIN technical_intakes i ON i.id=d.case_id
               JOIN maintenance_received_cases b ON b.case_id=d.case_id AND b.request_id=d.request_id
                 AND b.fee_quote_id::text=d.body->>'fee_quote_id'
                 AND to_jsonb(b.fee_quote_revision)=d.body->'fee_quote_revision'
               JOIN service_diagnosis_operations a
                 ON a.operation_id::text=d.body->>'operation_id'
                AND a.organization_id=d.organization_id AND a.actor_id=$9
                AND a.receipt=d.body AND a.receipt @> a.command
               JOIN maintenance_requests r
                 ON r.id=d.request_id AND r.organization_id=d.organization_id
                AND r.watch_id=d.watch_id AND r.actor_id=$10
               JOIN maintenance_request_operations o
                 ON o.operation_id=r.operation_id AND o.actor_id=r.actor_id
                AND o.organization_id=r.organization_id
               WHERE d.case_id=$1 AND d.assessment_id=$2 AND d.revision=$3
                 AND i.state='received' AND i.revision=$4
                 AND i.custody_receipt_id=$5 AND i.custody_revision=$6
                 AND i.order_id=$7 AND i.organization_id=d.organization_id
                 AND i.received_at=$8
                 AND i.private_record=$11::jsonb
                 AND d.body=$12::jsonb AND d.request_id=$13 AND d.watch_id=$14
                 AND r.state='submitted'
                 AND jsonb_typeof(r.private_request->'watch_revision')='number'
                 AND o.result @> jsonb_build_object(
                     'state', 'submitted', 'request_id', r.id, 'watch_id', r.watch_id,
                     'operation_id', r.operation_id, 'actor_id', r.actor_id,
                     'subject_id', r.actor_id, 'organization_id', r.organization_id,
                     'watch_revision', r.private_request->'watch_revision')
            """ + (' FOR SHARE OF d, i, b, a, r, o' if fence else ''),
        case_id, UUID(saved['assessment_id']), saved['assessment_revision'],
        saved['intake_revision'], facts.receipt_id, facts.receipt_revision,
        binding.order_id, intake['received_at'], UUID(saved['actor_id']), binding.buyer_id,
        json.dumps(decoded(intake['private_record'])), json.dumps(saved),
        binding.request_id, binding.watch_id)
    if not still_current:
        raise HTTPException(409)
    return {**saved, 'current': True, 'diagnosis_allowed': True}


@asynccontextmanager
async def hold_diagnosis(request, case_id, binding):
    try:
        async with unit_of_work(request.app.state.pool) as tx:
            # Bound the transaction even if the streaming response cannot clean up.
            await tx.execute("SET LOCAL transaction_timeout = '10s'")
            await tx.execute("SET LOCAL idle_in_transaction_session_timeout = '10s'")
            acquired = await tx.fetchval(
                'SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))', f'diagnosis:{case_id}')
            if not acquired:
                raise HTTPException(503)
            saved = await current_diagnosis(request, tx, case_id, fence=True)
            for field in ('buyer_id', 'organization_id', 'case_revision', 'assessment_id', 'assessment_revision'):
                expected = getattr(binding, field)
                if saved[field] != (str(expected) if isinstance(expected, UUID) else expected):
                    raise HTTPException(409)
            yield {'authorization': binding.model_dump(mode='json'), 'diagnosis': saved}
    except (ConnectionError, TimeoutError, asyncpg.LockNotAvailableError, asyncpg.QueryCanceledError):
        raise HTTPException(503) from None


class DiagnosisFenceResponse(Response):
    media_type = 'application/x-ndjson'

    def __init__(self, request, case_id, binding):
        super().__init__(headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        del self.headers['content-length']
        self.request, self.case_id, self.binding = request, case_id, binding

    async def __call__(self, scope, receive, send):
        started = False
        try:
            async with asyncio.timeout(FENCE_TIMEOUT_SECONDS):
                async with hold_diagnosis(self.request, self.case_id, self.binding) as proof:
                    started = True
                    await send({'type': 'http.response.start', 'status': 200, 'headers': self.raw_headers})
                    await send({'type': 'http.response.body', 'body': json.dumps(proof).encode() + b'\n', 'more_body': True})
                    while (await receive())['type'] != 'http.disconnect':
                        pass
        except TimeoutError:
            if started:
                # Abort the stream when the authorization expires.
                raise
            raise HTTPException(503) from None


@router.post('/internal/v1/service-cases/{case_id}/diagnosis/authorization')
async def authorize_decision(case_id: UUID, body: DiagnosisAuthorization, request: Request):
    service(request, {'pricing'})
    return DiagnosisFenceResponse(request, case_id, body)
