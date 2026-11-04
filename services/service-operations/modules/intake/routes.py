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


def receipt_matches(receipt,body,org,now):
    return (receipt.id==body.custody_receipt_id and receipt.order_id==body.order_id
        and receipt.organization_id==org and receipt.received_at<=now)


async def receipt_for(body,org,request):
    if body.custody_receipt_id is None:
        return None
    response=await clients(request.app)['orders'].request('GET',f'/v1/custody/receipts/{body.custody_receipt_id}',headers={'Authorization':'Bearer '+bearer(request)})
    if isinstance(response,Unavailable) or response.status_code not in (200,401,403,404,409):
        raise HTTPException(503)
    if response.status_code==401:
        raise HTTPException(401)
    if response.status_code!=200:
        raise PublicError('custody_unconfirmed','Actual custody has not been confirmed.',status=409)
    try:
        receipt=Receipt.model_validate(response.json())
    except ValueError:
        raise HTTPException(503) from None
    if not receipt_matches(receipt,body,org,datetime.now(timezone.utc)):
        raise PublicError('custody_scope_mismatch','The custody receipt does not match this intake.',status=409)
    return receipt


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
    result['diagnosis_allowed']=result['state']=='received' and all(result['private_record'][field] for field in
        ('diagnostic_opening_permission','no_polish_acknowledged','fee_acknowledged'))
    result['authentication_result']=None
    result['work_result']=None
    return result


@router.get('/records')
async def records(request: Request,p=Depends(principal),offset:int=0):
    org=await organization(p,request,'intake.read')
    if offset<0 or offset>10000:
        raise HTTPException(422)
    async with request.app.state.pool.acquire() as tx:
        rows=await tx.fetch('''SELECT id,order_id,state,revision,created_at,updated_at FROM technical_intakes
            WHERE organization_id=$1 ORDER BY updated_at DESC,id LIMIT 50 OFFSET $2''',org,offset)
    return {'items':[dict(row) for row in rows],'next_offset':offset+50 if len(rows)==50 else None}


@router.get('/records/{record_id}')
async def detail(record_id:UUID,request:Request,p=Depends(principal)):
    org=await organization(p,request,'intake.read')
    async with request.app.state.pool.acquire() as tx:
        row=await tx.fetchrow('SELECT * FROM technical_intakes WHERE id=$1 AND organization_id=$2',record_id,org)
    if row is None:
        raise HTTPException(404)
    result=present(row)
    result['custody_verification']='awaiting_intake'
    if row['custody_receipt_id']:
        # A recorded receipt is historical evidence, not perpetual work authority.
        # Later custody facts can fence it; a failed fresh check must disable readiness.
        command=Intake.model_validate({**result['private_record'],'order_id':row['order_id'],
            'custody_receipt_id':row['custody_receipt_id']})
        try:
            receipt=await receipt_for(command,org,request)
            result['custody_verification']='current' if receipt and receipt.revision==row['custody_revision'] else 'unconfirmed'
        except HTTPException as error:
            if error.status_code==401:
                raise
            result['custody_verification']='unavailable'
        except PublicError:
            result['custody_verification']='unconfirmed'
        result['diagnosis_allowed']=result['diagnosis_allowed'] and result['custody_verification']=='current'
    return result


async def save(body,request,p,record_id=None):
    org=await organization(p,request,'intake.write')
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
            return json.loads(prior['result'])
        # B-08: receipt and scope are rechecked before the protected write.
        receipt=await receipt_for(body,org,request)
        state='received' if receipt else 'awaiting_intake'
        if record_id:
            row=await tx.fetchrow('SELECT * FROM technical_intakes WHERE id=$1 AND organization_id=$2 FOR UPDATE',record_id,org)
            if row is None:
                raise HTTPException(404)
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
        private=body.model_dump(mode='json',exclude={'order_id','custody_receipt_id'})
        if rev==1:
            await tx.execute('''INSERT INTO technical_intakes(id,organization_id,order_id,author_id,revision,state,custody_receipt_id,custody_revision,received_at,private_record)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)''',record_id,org,body.order_id,actor,rev,state,receipt.id if receipt else None,receipt.revision if receipt else None,receipt.received_at if receipt else None,json.dumps(private))
        else:
            await tx.execute('''UPDATE technical_intakes SET revision=$3,state=$4,custody_receipt_id=$5,custody_revision=$6,received_at=$7,private_record=$8::jsonb,updated_at=now()
                WHERE id=$1 AND organization_id=$2''',record_id,org,rev,state,receipt.id if receipt else None,receipt.revision if receipt else None,receipt.received_at if receipt else None,json.dumps(private))
        await tx.execute('INSERT INTO technical_intake_audit(id,record_id,actor_id,revision,state) VALUES($1,$2,$3,$4,$5)',uuid4(),record_id,actor,rev,state)
        result={'id':str(record_id),'revision':rev,'state':state,'diagnosis_allowed':bool(receipt and body.diagnostic_opening_permission and body.no_polish_acknowledged and body.fee_acknowledged),'authentication_result':None,'work_result':None}
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
