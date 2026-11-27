import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from bt_contracts_core.models import EventEnvelope
from bt_contracts.service.intake.intake_command import AssessmentCustody, Intake, IntakeOperationCommand, IntakeOperationReceipt, OpeningAcceptance
from bt_contracts_core.errors import PublicError
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from .dependencies import principal
from bt_contracts.service.intake.v1 import IntakeEvent
from .authority import diagnostic_opening_allowed
from .access import organization, record_access, readable_orders, require_private_assignment
from .current_provider import CurrentAuthority
from service_app.received_case import verify_submission
from bt_contracts.service.intake.current import CurrentCustodyReceipt, OpeningAuthority
from bt_contracts.service.intake.repair_fence import lock_case, physical_confirmation, require_mutable

router=APIRouter(prefix='/v1/intake',tags=['technical intake'])


def receipt_matches(receipt,body,org,now):
    return (receipt.id==body.custody_receipt_id and receipt.order_id==body.order_id
        and receipt.organization_id==org and receipt.received_at<=now)



async def receipt_for(body, org, request, actor):
    if body.custody_receipt_id is None:
        return None
    provider = getattr(request.app.state, 'intake_current_authority', None) or CurrentAuthority(request)
    check = getattr(provider, 'current_custody', CurrentAuthority(request).current_custody)
    if not callable(check):
        raise HTTPException(503)
    try:
        value = await asyncio.wait_for(
            check(actor, org, body.order_id, body.custody_receipt_id), timeout=1.2)
        if value is False:
            raise PublicError('custody_unconfirmed', 'Actual custody has not been confirmed.', status=409)
        receipt = CurrentCustodyReceipt.model_validate(value)
    except (OSError, ValueError):
        raise HTTPException(503) from None
    if (
        not receipt_matches(receipt, body, org, datetime.now(timezone.utc))
        or receipt.actor_id != actor
        or (receipt.watch_id, receipt.watch_revision, receipt.incident_revision)
        != (receipt.current_watch_id, receipt.current_watch_revision, receipt.current_incident_revision)
    ):
        raise PublicError('custody_scope_mismatch', 'The custody receipt does not match current intake.', status=409)
    return receipt


def operation(request,body,*,exclude=None):
    key=request.headers.get('Idempotency-Key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',key):
        raise PublicError('idempotency_required','Supply a stable request key.',status=400)
    if isinstance(body, Intake):
        exclude = set(exclude or ())
        for field in ('opening_acceptance', 'reviewed_assessment_custody', 'reviewed_receipt_revision'):
            if getattr(body, field) is None:
                exclude.add(field)
    expected=request.headers.get('If-Match','').strip('"')
    digest=hashlib.sha256((request.url.path+'\n'+expected+'\n'+body.model_dump_json(exclude=exclude)).encode()).hexdigest()
    return key,digest


def present(row):
    result=dict(row)
    result['private_record']=json.loads(result['private_record'])
    for field in ('custody_history', 'assessment_history', 'assessment_custody'):
        result['private_record'].pop(field, None)
    # The v1 receipt lacks current watch, incident and assignment bindings.
    # Preserve its history, but never infer diagnostic opening authority.
    result['diagnosis_allowed']=False
    result['authentication_result']=None
    result['work_result']=None
    return result


@router.get('/records')
async def records(request: Request,p=Depends(principal),offset:int=0):
    org=await organization(p,request,'intake.read')
    if offset<0 or offset>10000:
        raise HTTPException(422)
    order_ids=await readable_orders(p,request,org)
    active_scope = "organization_id=$1 AND order_id=ANY($2::uuid[]) AND private_record->>'currency'='USD'"
    async with request.app.state.pool.acquire() as tx:
        rows=await tx.fetch(f'''SELECT id,order_id,state,revision,created_at,updated_at,
            count(*) OVER () AS total FROM technical_intakes
            WHERE {active_scope}
            ORDER BY updated_at DESC,id LIMIT 50 OFFSET $3''',org,order_ids,offset)
        total=rows[0]['total'] if rows else await tx.fetchval(
            f'SELECT count(*) FROM technical_intakes WHERE {active_scope}',
            org,order_ids)
    return {'intake_contract':'current','items':[{key: value for key,value in row.items() if key!='total'} for row in rows],'total':total,'next_offset':offset+50 if offset+50<total else None}


@router.delete('/operations/{key}')
async def close_operation(key: str, request: Request, p=Depends(principal)):
    return await resolve_operation(key, request, p, close=True)


@router.get('/operations/{key}', response_model=IntakeOperationReceipt)
async def operation_receipt(key: str, request: Request, p=Depends(principal)):
    return await resolve_operation(key, request, p)


async def resolve_operation(key, request, p, *, close=False):
    org = await organization(p, request, 'intake.write')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', key):
        raise HTTPException(404)
    actor = p.actor.subject_id
    async with unit_of_work(request.app.state.pool, lock_key=f'intake:{actor}:{org}:{key}') as tx:
        row = await tx.fetchrow('''SELECT o.request_hash, o.result, r.order_id, r.id AS record_id
            FROM technical_intake_operations o
            LEFT JOIN technical_intakes r ON r.organization_id=o.organization_id
                AND r.id=COALESCE(o.result->>'record_id', o.result->>'id')::uuid
            WHERE o.actor_id=$1 AND o.organization_id=$2 AND o.key=$3''', actor, org, key)
        if row is None or row['request_hash'] == 'closed':
            if not close:
                raise PublicError('operation_missing', 'No intake receipt is available for this operation.', status=404)
            await tx.execute('''INSERT INTO technical_intake_operations
                (actor_id, organization_id, key, request_hash, result)
                VALUES ($1,$2,$3,'closed','{}'::jsonb)
                ON CONFLICT (actor_id, organization_id, key) DO NOTHING''', actor, org, key)
            return {'operation_id': key, 'organization_id': org, 'state': 'closed'}
        if row['order_id'] is None:
            raise HTTPException(503)
        await record_access(p, request, org, row['order_id'], 'write')
        result = json.loads(row['result'])
    receipt = {'operation_id': key, 'organization_id': org, 'record_id': row['record_id'],
               'order_id': row['order_id'], 'revision': result['revision'],
               'kind': 'evidence' if 'record_id' in result else 'save'}
    if 'maintenance_request_id' in result:
        receipt['maintenance_request_id'] = result['maintenance_request_id']
    return receipt


@router.get('/records/{record_id}')
async def detail(record_id:UUID,request:Request,p=Depends(principal),review_receipt_id: UUID | None = None):
    org=await organization(p,request,'intake.read')
    # Serialize this decision with saves and evidence writes for the same record.
    async with unit_of_work(request.app.state.pool) as tx:
        row=await tx.fetchrow('''SELECT i.*, b.request_id AS maintenance_request_id
            FROM technical_intakes i LEFT JOIN maintenance_received_cases b ON b.case_id=i.id
            WHERE i.id=$1 AND i.organization_id=$2 FOR SHARE OF i''',record_id,org)
        if row is None:
            raise HTTPException(404)
        await require_private_assignment(p,request,org,row['order_id'],'read')
        result=present(row)
        if review_receipt_id is not None:
            await require_private_assignment(p,request,org,row['order_id'],'write')
            if not row['custody_receipt_id'] or result['private_record'].get('currency') != 'USD':
                raise PublicError('stale_receipt_revision', 'A recorded USD intake is required.', status=409)
            command = Intake.model_validate({**result['private_record'], 'order_id':row['order_id'],
                'custody_receipt_id':review_receipt_id})
            receipt = await receipt_for(command,org,request,p.actor.subject_id)
            if receipt is None or receipt.revision <= row['custody_revision']:
                raise PublicError('stale_receipt_revision', 'Supply a newer verified custody receipt.', status=409)
            return {'revision': row['revision'], 'receipt_revision_for_review': assessment_custody(receipt)}
        result['custody_verification']='awaiting_intake'
        receipt = None
        if row['custody_receipt_id']:
            # A recorded receipt is historical evidence, not perpetual work authority.
            # Later custody facts can fence it; a failed fresh check must disable readiness.
            command=Intake.model_validate({**result['private_record'],'order_id':row['order_id'],
                'custody_receipt_id':row['custody_receipt_id']})
            try:
                receipt=await receipt_for(command,org,request,p.actor.subject_id)
                result['custody_verification']='current' if receipt and receipt.revision==row['custody_revision'] else 'unconfirmed'
                if (receipt and receipt.revision > row['custody_revision']
                        and result['private_record']['currency'] == 'USD'):
                    result['receipt_revision_for_review'] = assessment_custody(receipt)
            except HTTPException as error:
                if error.status_code==401:
                    raise
                result['custody_verification']='unavailable'
            except PublicError:
                result['custody_verification']='unconfirmed'
        current_custody = receipt if result['custody_verification'] == 'current' else None
        if json.loads(row['private_record']).get('assessment_custody') != assessment_custody(current_custody) or current_custody is None:
            result['private_record']['assessed_issue'] = ''
        result['assessment_allowed'] = (
            result['custody_verification'] == 'current'
            and result['private_record']['currency'] == 'USD'
            and await may_record_assessment(p, request, org, row['order_id'])
        )
        if result['assessment_allowed']:
            result['current_assessment_custody'] = assessment_custody(current_custody)
        result['diagnosis_allowed']=(result['custody_verification']=='current'
            and await current_opening(receipt,p,request,result['private_record'], result=result,
                tx=tx, linked_request=row.get('maintenance_request_id')))
        return result


def assessment_custody(receipt):
    if receipt is None:
        return None
    return AssessmentCustody(
        watch_id=receipt.watch_id, watch_revision=receipt.watch_revision,
        receipt_id=receipt.id, receipt_revision=receipt.revision,
        incident_revision=receipt.incident_revision,
    ).model_dump(mode='json')


async def may_record_assessment(p, request, org, order_id):
    try:
        await record_access(p, request, org, order_id, 'assess')
    except HTTPException as error:
        if error.status_code in (403, 503):
            return False
        raise
    return True


OPENING_FLAGS = ('diagnostic_opening_permission', 'fee_acknowledged', 'no_polish_acknowledged')
OPENING_FIELDS = (*OPENING_FLAGS, 'fee_minor', 'opening_acceptance')


def opening_values(private):
    defaults = (False, False, False, 0, None)
    return tuple(private.get(field, default) for field, default in zip(OPENING_FIELDS, defaults))


async def assigned_opening(receipt, p, request):
    if receipt is None:
        return None
    provider = getattr(request.app.state, 'intake_current_authority', None) or CurrentAuthority(request)
    check = getattr(provider, 'current', None)
    if not callable(check):
        return None
    try:
        facts = OpeningAuthority.model_validate(await asyncio.wait_for(
            check(p.actor.subject_id, receipt.organization_id, receipt.order_id), timeout=1.2))
    except (OSError, ValueError):
        return None
    if (
        facts.actor_id, facts.organization_id, facts.order_id, facts.receipt_id,
        facts.receipt_revision, facts.watch_id, facts.watch_revision,
        facts.incident_revision, facts.received_at
    ) != (
        p.actor.subject_id, receipt.organization_id, receipt.order_id, receipt.id,
        receipt.revision, receipt.watch_id, receipt.watch_revision,
        receipt.incident_revision, receipt.received_at
    ):
        return None
    if not facts.current or not facts.assigned:
        return None
    advertised = (facts.current_watch_id, facts.current_watch_revision, facts.current_incident_revision)
    if advertised != (None, None, None) and advertised != (
            receipt.watch_id, receipt.watch_revision, receipt.incident_revision):
        return None
    return facts


def permitted_opening(receipt, facts):
    if receipt is None or facts is None or not diagnostic_opening_allowed(
        receipt=facts.model_dump(), watch_id=receipt.watch_id,
        watch_revision=receipt.watch_revision, organization_id=receipt.organization_id,
        incident_revision=receipt.incident_revision, now=datetime.now(timezone.utc),
        assigned=facts.assigned, permission=facts.permission,
        opening_permission=facts.customer_opening_permission,
        fee_acknowledged=facts.accepted_assessment_fee,
        no_polish_acknowledged=facts.customer_no_polish_acknowledged,
    ):
        return None
    return facts


def matches_opening(private, facts):
    if facts is None:
        return False
    try:
        recorded = OpeningAcceptance.model_validate(private.get('opening_acceptance'))
    except ValueError:
        return False
    return (
        recorded.model_dump() == facts.model_dump(include=set(OpeningAcceptance.model_fields))
        and private['fee_minor'] == facts.accepted_fee_minor
        and all(private[field] is True for field in OPENING_FLAGS)
    )


async def current_opening(receipt, p, request, private, *, result, tx=None, linked_request=None):
    if private['currency'] != 'USD':
        return False
    facts = permitted_opening(receipt, await assigned_opening(receipt, p, request))
    if facts is None or not await confirmed_opening(tx, facts, linked_request):
        return False
    result['current_opening_acceptance'] = facts.model_dump(
        mode='json', include=set(OpeningAcceptance.model_fields))
    result['current_opening_fee_minor'] = facts.accepted_fee_minor
    return matches_opening(private, facts)


async def confirmed_opening(tx, facts, linked_request):
    if linked_request is None and facts.maintenance_request_id is None:
        return True
    return bool(linked_request and linked_request == facts.maintenance_request_id
                and await physical_confirmation(tx, linked_request, facts))


async def save(body,request,p,record_id=None):
    org=await organization(p,request,'intake.write')
    if body.currency!='USD':
        raise PublicError('currency_reissue_required','Review and reissue this intake in US dollars.',status=409)
    actor=p.actor.subject_id
    key,digest=operation(request,body)
    expected=None
    if record_id:
        raw=request.headers.get('If-Match','').strip('"')
        if not re.fullmatch(r'[1-9][0-9]{0,9}',raw):
            raise PublicError('revision_required','Reload the intake before changing it.',status=428)
        expected=int(raw)
    async with unit_of_work(request.app.state.pool,lock_key=f'intake:{actor}:{org}:{key}') as tx:
        # Verify record scope while the row is locked and before replay or write.
        row=None
        existing=None
        if record_id:
            await lock_case(tx, record_id)
            row=await tx.fetchrow('SELECT * FROM technical_intakes WHERE id=$1 AND organization_id=$2 FOR UPDATE',record_id,org)
            if row is None:
                raise HTTPException(404)
            await require_private_assignment(p,request,org,row['order_id'],'write')
            if row['order_id']!=body.order_id:
                raise PublicError('immutable_custody','The order cannot be replaced.',status=409)
        else:
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'intake-order:{org}:{body.order_id}')
            await record_access(p,request,org,body.order_id,'write')
            existing=await tx.fetchrow('SELECT id FROM technical_intakes WHERE organization_id=$1 AND order_id=$2',org,body.order_id)
        prior=await tx.fetchrow('SELECT * FROM technical_intake_operations WHERE actor_id=$1 AND organization_id=$2 AND key=$3',actor,org,key)
        if prior:
            if prior['request_hash']!=digest:
                raise PublicError('idempotency_conflict','This request key has another payload.',status=409)
            result=json.loads(prior['result'])
            return {**result, 'diagnosis_allowed': False, 'operation_id': key,
                    'organization_id': str(org), 'order_id': str(body.order_id)}
        if row is None and existing:
            raise PublicError('intake_exists','Open the existing intake for this order.',status=409)
        if record_id is not None:
            await require_mutable(tx, record_id)
        receipt=await receipt_for(body,org,request,actor)
        state='received' if receipt else 'awaiting_intake'
        previous = {}
        if row is not None:
            previous = json.loads(row['private_record'])
            if previous.get('currency')!='USD':
                raise PublicError('currency_reissue_required','This legacy record is read-only pending explicit reissue.',status=409)
            if row['revision']!=expected:
                raise PublicError('stale_revision','The intake changed. Reload before retrying.',status=409)
            if row['custody_receipt_id'] and (receipt is None or receipt.revision < row['custody_revision']
                    or (receipt.id != row['custody_receipt_id'] and receipt.revision == row['custody_revision'])):
                raise PublicError('immutable_custody','Supply a newer verified custody receipt.',status=409)
            rev=expected+1
        else:
            record_id=uuid4()
            rev=1
        private=body.model_dump(mode='json',exclude={
            'order_id','custody_receipt_id','reviewed_assessment_custody','reviewed_receipt_revision'})
        opening = await assigned_opening(receipt, p, request)
        opening_confirmed = False
        values = opening_values(private)
        if values != opening_values(previous) and any(values):
            opening_confirmed = matches_opening(private, permitted_opening(receipt, opening))
            if not opening_confirmed:
                raise PublicError('opening_acceptance_unconfirmed',
                                  'Review the current customer acknowledgements and fee.', status=409)
        prior_assessment = previous.get('assessed_issue', '')
        prior_binding = previous.get('assessment_custody')
        binding = assessment_custody(receipt)
        finding = private['assessed_issue']
        if row is None and receipt is None and finding in {'SAMPLE not assessed', 'Assessment not started'}:
            finding = ''
        assessment_history = previous.get('assessment_history', [])
        same_custody = binding is not None and binding == prior_binding
        if prior_assessment and (not same_custody or finding != prior_assessment):
            assessment_history.append({'finding': prior_assessment, 'custody': prior_binding,
                                       'intake_revision': row['revision']})
        reviewed = body.reviewed_assessment_custody
        if reviewed is not None:
            if reviewed.model_dump(mode='json') != binding:
                raise PublicError('stale_assessment_custody',
                                  'Review current custody before recording findings.', status=409)
            await record_access(p, request, org, body.order_id, 'assess')
        if reviewed is None and not same_custody and finding == prior_assessment:
            # Historic text echoed by an open editor cannot confirm current findings.
            finding = ''
        if reviewed is None and finding != (prior_assessment if same_custody else ''):
            if receipt is None:
                raise PublicError('assessment_requires_custody',
                                  'Confirm current custody before recording findings.', status=409)
            raise PublicError('stale_assessment_custody',
                              'Review current custody before recording findings.', status=409)
        advancing_receipt = (row is not None and row['custody_receipt_id'] is not None
                             and receipt is not None
                             and receipt.revision > row['custody_revision'])
        reviewed_receipt = body.reviewed_receipt_revision
        if advancing_receipt or reviewed_receipt is not None:
            if (not advancing_receipt or reviewed_receipt is None
                    or reviewed_receipt.model_dump(mode='json') != assessment_custody(receipt)):
                raise PublicError('stale_receipt_revision',
                                  'Review the newer verified custody receipt before saving.', status=409)
        private['assessed_issue'] = finding
        if finding:
            private['assessment_custody'] = binding
        if assessment_history:
            private['assessment_history'] = assessment_history
        if row is not None:
            history = previous.get('custody_history', [])
            if row['custody_receipt_id'] and receipt.revision > row['custody_revision']:
                history.append({
                    'receipt_id': str(row['custody_receipt_id']),
                    'receipt_revision': row['custody_revision'],
                    'intake_revision': row['revision'],
                    'received_at': row['received_at'].isoformat(),
                })
            if history:
                private['custody_history'] = history
        linked_request = opening.maintenance_request_id if opening else None
        link = (await tx.fetchrow('SELECT * FROM maintenance_received_cases WHERE case_id=$1', record_id)
                if row is not None else None)
        if link and (opening is None or (link['request_id'], link['fee_quote_id'], link['fee_quote_revision']) != (
                linked_request, opening.quote_id, opening.quote_revision)):
            raise PublicError('stale_case_binding', 'The received maintenance case changed.', status=409)
        if linked_request:
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                             f'maintenance-received:{linked_request}')
            await verify_submission(request, tx, opening, linked_request)
            bound_case = await tx.fetchval('SELECT case_id FROM maintenance_received_cases WHERE request_id=$1', linked_request)
            if bound_case is not None and bound_case != record_id:
                raise PublicError('stale_case_binding', 'The request already has another received case.', status=409)
        if rev==1:
            await tx.execute('''INSERT INTO technical_intakes(id,organization_id,order_id,author_id,revision,state,custody_receipt_id,custody_revision,received_at,private_record)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)''',record_id,org,body.order_id,actor,rev,state,receipt.id if receipt else None,receipt.revision if receipt else None,receipt.received_at if receipt else None,json.dumps(private))
        else:
            await tx.execute('''UPDATE technical_intakes SET revision=$3,state=$4,custody_receipt_id=$5,custody_revision=$6,received_at=$7,private_record=$8::jsonb,updated_at=now()
                WHERE id=$1 AND organization_id=$2''',record_id,org,rev,state,receipt.id if receipt else None,receipt.revision if receipt else None,receipt.received_at if receipt else None,json.dumps(private))
        if linked_request and not link:
            await tx.execute('INSERT INTO maintenance_received_cases VALUES($1,$2,$3,$4)',
                             record_id, linked_request, opening.quote_id, opening.quote_revision)
        await tx.execute('INSERT INTO technical_intake_audit(id,record_id,actor_id,revision,state) VALUES($1,$2,$3,$4,$5)',uuid4(),record_id,actor,rev,state)
        result={'id':str(record_id),'revision':rev,'state':state,'authentication_result':None,'work_result':None}
        if linked_request:
            result['maintenance_request_id'] = str(linked_request)
        await enqueue(tx,EventEnvelope(type='service-operations.intake.recorded.v1',source='service-operations',subject=str(record_id),request_id=request.state.request_id,
            data=IntakeEvent(record_id=record_id,order_id=body.order_id,organization_id=org,state=state,revision=rev,
                custody_receipt_id=receipt.id if receipt else None).model_dump(mode='json')),['orders','communications'])
        await tx.execute('INSERT INTO technical_intake_operations(actor_id,organization_id,key,request_hash,result) VALUES($1,$2,$3,$4,$5::jsonb)',actor,org,key,digest,json.dumps(result))
        return {**result, 'diagnosis_allowed': bool(opening_confirmed and
                    await confirmed_opening(tx, opening, linked_request)), 'operation_id': key,
                'organization_id': str(org), 'order_id': str(body.order_id)}


@router.post('/records',status_code=201)
async def create(body: Intake | IntakeOperationCommand, request: Request,
                 response: Response, p=Depends(principal)):
    if isinstance(body, IntakeOperationCommand):
        result = await resolve_operation(body.operation_id, request, p, close=body.action == 'close')
        response.status_code = 200
        return result
    return await save(body, request, p)


@router.put('/records/{record_id}')
async def update(record_id:UUID,body:Intake,request:Request,p=Depends(principal)):
    return await save(body,request,p,record_id)
