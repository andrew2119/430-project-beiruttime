from .current_provider import CurrentAuthority
from service_app.received_case import case_binding, verify_submission
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_bulkheads import Unavailable
from bt_contracts_core.models import EventEnvelope
from bt_contracts.service.intake.v1 import Intake, Receipt, IntakeEvent
from bt_contracts_core.errors import PublicError
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from .dependencies import principal, clients, bearer
from .authority import diagnostic_opening_allowed
from .access import record_access, readable_orders
from bt_contracts.service.intake.current import OpeningAuthority

router=APIRouter(prefix='/v1/intake',tags=['technical intake'])


async def organization(p, request, permission):
    org=p.actor.organization_id
    if org is None:
        raise HTTPException(403)
    canonical={'intake.read':'business.records.read','intake.write':'business.jobs.write'}[permission]
    # Explicit legacy intake grants remain supported; current business capabilities
    # are checked in the same selected organization, never combined across businesses.
    legacy=any(grant.organization_id==org and permission in grant.permissions for grant in p.organization_grants)
    require_scope(p,permission if legacy else canonical,org)
    response=await clients(request.app)['service-operations'].request('GET',f'/v1/directory/providers/{org}',headers={'Authorization':'Bearer '+bearer(request)})
    if isinstance(response,Unavailable) or response.status_code not in (200,401,403,404,409):
        raise HTTPException(503)
    if response.status_code==401:
        raise HTTPException(401)
    if response.status_code!=200:
        raise HTTPException(403)
    try:
        provider=response.json()
        valid=(UUID(str(provider['organization_id']))==org and provider['official'] is True and provider['active'] is True and provider['kind'] in ('brand','dealer'))
    except (ValueError,TypeError,KeyError):
        raise HTTPException(503) from None
    if not valid:
        raise HTTPException(403)
    return org


def receipt_matches(receipt, body, org, now):
    return (receipt.id, receipt.order_id, receipt.organization_id) == (
        body.custody_receipt_id, body.order_id, org) and receipt.received_at <= now


async def receipt_for(body, org, request):
    response = await clients(request.app)['orders'].request(
        'GET', f'/v1/custody/receipts/{body.custody_receipt_id}',
        headers={'Authorization': 'Bearer ' + bearer(request)},
    )
    if isinstance(response, Unavailable) or response.status_code not in (200, 401, 403, 404, 409):
        raise HTTPException(503)
    if response.status_code == 401:
        raise HTTPException(401)
    if response.status_code != 200:
        raise PublicError('custody_unconfirmed', 'Actual custody has not been confirmed.', status=409)
    try:
        receipt = Receipt.model_validate(response.json())
    except ValueError:
        raise HTTPException(503) from None
    if not receipt_matches(receipt, body, org, datetime.now(timezone.utc)):
        raise PublicError('custody_scope_mismatch', 'The custody receipt does not match this intake.', status=409)
    return receipt


async def assigned_opening(body, actor, org, request, receipt):
    provider = getattr(request.app.state, 'intake_current_authority', None) or CurrentAuthority(request)
    try:
        facts = OpeningAuthority.model_validate(await asyncio.wait_for(
            provider.current(actor, org, body.order_id), timeout=1.2))
    except (TimeoutError, ConnectionError, ValueError):
        raise HTTPException(503) from None
    if not facts.current or not facts.assigned:
        raise PublicError('custody_unconfirmed', 'Actual custody has not been confirmed.', status=409)
    if (facts.actor_id, facts.receipt_id, facts.order_id, facts.organization_id,
            facts.receipt_revision, facts.received_at) != (
            actor, receipt.id, receipt.order_id, receipt.organization_id,
            receipt.revision, receipt.received_at):
        raise PublicError('custody_scope_mismatch', 'The custody receipt does not match this intake.', status=409)
    return facts


def operation(request,body):
    key=request.headers.get('Idempotency-Key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',key):
        raise PublicError('idempotency_required','Supply a stable request key.',status=400)
    expected=request.headers.get('If-Match','').strip('"')
    digest=hashlib.sha256((request.url.path+'\n'+expected+'\n'+body.model_dump_json()).encode()).hexdigest()
    return key,digest


def present(row):
    result=dict(row)
    result['private_record']=json.loads(result['private_record'])
    if result.get('maintenance_request_id') is None:
        result.pop('maintenance_request_id', None)
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
    async with request.app.state.pool.acquire() as tx:
        rows=await tx.fetch('''SELECT id,order_id,state,revision,created_at,updated_at FROM technical_intakes
            WHERE organization_id=$1 AND order_id=ANY($2::uuid[]) ORDER BY updated_at DESC,id LIMIT 50 OFFSET $3''',org,order_ids,offset)
        total=await tx.fetchval('SELECT count(*) FROM technical_intakes WHERE organization_id=$1 AND order_id=ANY($2::uuid[])',org,order_ids)
    return {'items':[dict(row) for row in rows],'total':total,'next_offset':offset+50 if offset+50<total else None}


@router.get('/records/{record_id}')
async def detail(record_id:UUID,request:Request,p=Depends(principal)):
    org=await organization(p,request,'intake.read')
    async with request.app.state.pool.acquire() as tx:
        row=await tx.fetchrow('''SELECT i.*, b.request_id AS maintenance_request_id
            FROM technical_intakes i LEFT JOIN maintenance_received_cases b ON b.case_id=i.id
            WHERE i.id=$1 AND i.organization_id=$2''',record_id,org)
    if row is None:
        raise HTTPException(404)
    await record_access(p,request,org,row['order_id'],'read')
    result=present(row)
    result['custody_verification'] = 'awaiting_intake'
    if row['state'] != 'received' or not row['custody_receipt_id']:
        return result
    body = Intake.model_validate({**result['private_record'], 'order_id': row['order_id'],
                                  'custody_receipt_id': row['custody_receipt_id']})
    try:
        receipt = await receipt_for(body, org, request)
    except HTTPException as error:
        if error.status_code == 401:
            raise
        result['custody_verification'] = 'unavailable'
    except PublicError:
        result['custody_verification'] = 'unconfirmed'
    else:
        if (receipt.revision, receipt.received_at) == (row['custody_revision'], row['received_at']):
            result['custody_verification'] = 'current'
            try:
                await record_access(p,request,org,row['order_id'],'write')
                facts = await assigned_opening(body, p.actor.subject_id, org, request, receipt)
                if current_opening(facts, org, result['private_record']):
                    if facts.maintenance_request_id or row['maintenance_request_id']:
                        async with request.app.state.pool.acquire() as tx:
                            await case_binding(request, tx, record_id, facts)
                    result['diagnosis_allowed'] = True
            except (HTTPException, PublicError):
                pass
        else:
            result['custody_verification'] = 'unconfirmed'
    return result


def current_opening(facts, org, private):
    if private['currency']!='USD' or private['fee_minor']!=facts.accepted_fee_minor:
        return False
    return diagnostic_opening_allowed(receipt=facts.model_dump(),watch_id=facts.watch_id,
        watch_revision=facts.watch_revision,organization_id=org,incident_revision=facts.incident_revision,
        now=datetime.now(timezone.utc),assigned=facts.assigned,permission=facts.permission,
        opening_permission=private['diagnostic_opening_permission'] and facts.customer_opening_permission,
        fee_acknowledged=private['fee_acknowledged'] and facts.accepted_assessment_fee,
        no_polish_acknowledged=private['no_polish_acknowledged'] and facts.customer_no_polish_acknowledged)


async def save(body,request,p,record_id=None):
    org=await organization(p,request,'intake.write')
    if body.currency!='USD':
        raise PublicError('currency_reissue_required','Review and reissue this intake in US dollars.',status=409)
    await record_access(p,request,org,body.order_id,'write')
    actor=p.actor.subject_id
    key,digest=operation(request,body)
    expected=None
    if record_id:
        raw=request.headers.get('If-Match','').strip('"')
        if not re.fullmatch(r'[1-9][0-9]{0,9}',raw):
            raise PublicError('revision_required','Reload the intake before changing it.',status=428)
        expected=int(raw)
    async with unit_of_work(request.app.state.pool,lock_key=f'intake:{actor}:{org}:{key}') as tx:
        prior=await tx.fetchrow('SELECT * FROM technical_intake_operations WHERE actor_id=$1 AND organization_id=$2 AND key=$3',actor,org,key)
        if prior:
            if prior['request_hash']!=digest:
                raise PublicError('idempotency_conflict','This request key has another payload.',status=409)
            result=json.loads(prior['result'])
            # A historical receipt cannot grant current diagnostic permission.
            result['diagnosis_allowed']=False
            return result
        if record_id:
            row=await tx.fetchrow('SELECT * FROM technical_intakes WHERE id=$1 AND organization_id=$2 FOR UPDATE',record_id,org)
            if row is None:
                raise HTTPException(404)
            if json.loads(row['private_record']).get('currency')!='USD':
                raise PublicError('currency_reissue_required','This legacy record is read-only pending explicit reissue.',status=409)
            if row['revision']!=expected:
                raise PublicError('stale_revision','The intake changed. Reload before retrying.',status=409)
            if row['order_id']!=body.order_id or row['custody_receipt_id'] and row['custody_receipt_id']!=body.custody_receipt_id:
                raise PublicError('immutable_custody','Order and acknowledged custody cannot be replaced.',status=409)
            rev=expected+1
        else:
            # One intake per represented organization/order, even under racing keys.
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'intake-order:{org}:{body.order_id}')
            if await tx.fetchval('SELECT id FROM technical_intakes WHERE organization_id=$1 AND order_id=$2',org,body.order_id):
                raise PublicError('intake_exists','Open the existing intake for this order.',status=409)
            record_id=uuid4()
            rev=1
        receipt = opening = link = None
        if body.custody_receipt_id:
            receipt = await receipt_for(body, org, request)
            link = await tx.fetchrow(
                'SELECT * FROM maintenance_received_cases WHERE case_id=$1', record_id)
            try:
                opening = await assigned_opening(body, actor, org, request, receipt)
            except HTTPException as error:
                if link or error.status_code != 503:
                    raise
            except PublicError as error:
                if link or error.code != 'custody_unconfirmed':
                    raise
                # The audited receipt remains valid without diagnostic opening authority.
        linked_request = opening.maintenance_request_id if opening else None
        if opening and link and (link['request_id'], link['fee_quote_id'], link['fee_quote_revision']) != (
                linked_request, opening.quote_id, opening.quote_revision):
            raise HTTPException(409)
        if linked_request:
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                             f'maintenance-received:{linked_request}')
            await verify_submission(request, tx, opening, linked_request)
            bound_case = await tx.fetchval(
                'SELECT case_id FROM maintenance_received_cases WHERE request_id=$1', linked_request)
            if bound_case is not None and bound_case != record_id:
                raise HTTPException(409)
        state='received' if receipt else 'awaiting_intake'
        private=body.model_dump(mode='json',exclude={'order_id','custody_receipt_id'})
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
        result={'id':str(record_id),'revision':rev,'state':state,'diagnosis_allowed':False,'authentication_result':None,'work_result':None}
        if linked_request:
            result['maintenance_request_id'] = str(linked_request)
        await enqueue(tx,EventEnvelope(type='service-operations.intake.recorded.v1',source='service-operations',subject=str(record_id),request_id=request.state.request_id,
            data=IntakeEvent(record_id=record_id,order_id=body.order_id,organization_id=org,state=state,revision=rev,
                custody_receipt_id=receipt.id if receipt else None).model_dump(mode='json')),['orders','communications'])
        await tx.execute('INSERT INTO technical_intake_operations(actor_id,organization_id,key,request_hash,result) VALUES($1,$2,$3,$4,$5::jsonb)',actor,org,key,digest,json.dumps(result))
        return result


@router.post('/records',status_code=201)
async def create(body:Intake,request:Request,p=Depends(principal)):
    return await save(body,request,p)


@router.put('/records/{record_id}')
async def update(record_id:UUID,body:Intake,request:Request,p=Depends(principal)):
    return await save(body,request,p,record_id)
