import hashlib
import json
import re
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_contracts.trust.moderation.v1 import Report, Decision, Appeal, AssignmentRelease, DecisionEvent
from bt_bulkheads import Unavailable
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from .dependencies import principal, clients, bearer

router = APIRouter(prefix='/v1/moderation', tags=['moderation'])


def operation(request, body):
    key = request.headers.get('Idempotency-Key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',key):
        raise PublicError('idempotency_required','Supply a stable request key.',status=400)
    expected=request.headers.get('If-Match','').strip('"')
    digest=hashlib.sha256((request.url.path+'\n'+expected+'\n'+json.dumps(body,sort_keys=True,default=str)).encode()).hexdigest()
    return key,digest


def revision(request):
    raw=request.headers.get('If-Match','').strip('"')
    if not re.fullmatch(r'[1-9][0-9]{0,9}',raw):
        raise PublicError('revision_required','Reload the record before changing it.',status=428)
    return int(raw)


async def replay(tx, actor, key, digest):
    row=await tx.fetchrow('SELECT * FROM moderation_operations WHERE actor_id=$1 AND key=$2',actor,key)
    if row:
        if row['request_hash']!=digest:
            raise PublicError('idempotency_conflict','This request key has another payload.',status=409)
        return json.loads(row['result'])


async def remember(tx,actor,key,digest,result):
    await tx.execute('INSERT INTO moderation_operations(actor_id,key,request_hash,result) VALUES($1,$2,$3,$4::jsonb)',actor,key,digest,json.dumps(result))
    return result


async def case_row(tx, case_id):
    row=await tx.fetchrow('SELECT * FROM moderation_cases WHERE id=$1 FOR UPDATE',case_id)
    if row is None:
        raise HTTPException(404)
    return row


def independent(row, p):
    require_scope(p,'moderation.review')
    if p.actor.subject_id in (row['subject_id'],row['reporter_id']):
        raise PublicError('independent_review_required','Another reviewer must handle this case.',status=403)


def check_revision(row, expected):
    if row['revision']!=expected:
        raise PublicError('stale_revision','The case changed. Reload before retrying.',status=409)


@router.post('/reports',status_code=201)
async def report(body: Report, request: Request, p=Depends(principal)):
    actor=p.actor.subject_id
    key,digest=operation(request,body.model_dump(mode='json'))
    # B-09: serialize the first outcome, including retries racing the original.
    async with unit_of_work(request.app.state.pool,lock_key=f'moderation-report:{actor}') as tx:
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'moderation:{actor}:{key}')
        prior=await replay(tx,actor,key,digest)
        if prior is not None:
            return prior
        count=await tx.fetchval("SELECT count(*) FROM moderation_cases WHERE reporter_id=$1 AND created_at>now()-interval '10 minutes'",actor)
        if count>=10:
            raise PublicError('report_limit','Wait before submitting another report.',status=429)
        subject=body.target_id
        if body.target_kind in ('listing','message','user'):
            service={'listing':'catalog','message':'communications','user':'identity'}[body.target_kind]
            path={'listing':f'/v1/listings/{body.target_id}/report-subject','message':f'/v1/messages/{body.target_id}',
                'user':f'/v1/accounts/{body.target_id}/report-subject'}[body.target_kind]
            response=await clients(request.app)[service].request('GET',path,headers={'Authorization':'Bearer '+bearer(request)})
            if isinstance(response,Unavailable):
                raise HTTPException(503)
            if response.status_code==401:
                raise HTTPException(401)
            if response.status_code in (403,404):
                raise HTTPException(404)
            if response.status_code!=200:
                raise HTTPException(503)
            try:
                payload=response.json()
                subject=UUID(str(payload[{'catalog':'seller_id','communications':'sender_id','identity':'subject_id'}[service]]))
                if service=='identity' and subject!=body.target_id:
                    raise ValueError('Mismatched subject')
                if service=='catalog' and UUID(str(payload.get('id',payload.get('listing_id',''))))!=body.target_id:
                    raise ValueError('Mismatched listing')
            except (ValueError,KeyError,TypeError):
                raise HTTPException(503) from None
        case_id=uuid4()
        await tx.execute('''INSERT INTO moderation_cases(id,reporter_id,target_kind,target_id,subject_id,category,evidence)
            VALUES($1,$2,$3,$4,$5,$6,$7)''',case_id,actor,body.target_kind,body.target_id,subject,body.category,body.evidence)
        return await remember(tx,actor,key,digest,{'id':str(case_id),'revision':1,'status':'open'})


@router.get('/cases')
async def queue(request: Request, p=Depends(principal), offset: int=0):
    require_scope(p,'moderation.review')
    if offset<0 or offset>10000:
        raise HTTPException(422)
    can_assign='moderation.assign' in p.permissions
    async with request.app.state.pool.acquire() as tx:
        rows=await tx.fetch('''SELECT id,target_kind,target_id,category,status,revision,assigned_to,created_at
            FROM moderation_cases WHERE subject_id<>$1 AND reporter_id<>$1 AND ($3::boolean OR assigned_to IS NULL OR assigned_to=$1)
            ORDER BY created_at,id LIMIT 50 OFFSET $2''',p.actor.subject_id,offset,can_assign)
    return {'items':[{**dict(r),'can_release':can_assign and r['assigned_to'] is not None,
        'can_claim':r['assigned_to'] in (None,p.actor.subject_id)} for r in rows],
        'next_offset':offset+50 if len(rows)==50 else None}


@router.get('/cases/{case_id}')
async def detail(case_id: UUID, request: Request, p=Depends(principal), before_revision: int | None=None):
    if before_revision is not None and not 1<=before_revision<=2147483647:
        raise HTTPException(422)
    async with request.app.state.pool.acquire() as tx:
        row=await tx.fetchrow('SELECT * FROM moderation_cases WHERE id=$1',case_id)
        if row is None:
            raise HTTPException(404)
        reporter=p.actor.subject_id==row['reporter_id']
        subject=p.actor.subject_id==row['subject_id']
        reviewer=not reporter and not subject
        if reviewer:
            independent(row,p)
            if row['assigned_to']!=p.actor.subject_id:
                raise AccessDenied('Unassigned reviewer')
        audit=await tx.fetch('''SELECT actor_id,kind,reason,revision,created_at FROM moderation_audit
            WHERE case_id=$1 AND ($2::integer IS NULL OR revision<$2) ORDER BY revision DESC LIMIT 101''',case_id,before_revision)
        older_available=len(audit)>100
        audit=list(reversed(audit[:100]))
        delivery='none'
        if row['last_event_id']:
            delivered=await tx.fetchval('SELECT bool_and(delivered_at IS NOT NULL) FROM outbox WHERE event_id=$1',row['last_event_id'])
            delivery='acknowledged' if delivered else 'pending'
    signals=[]
    if reviewer:
        async with request.app.state.pool.acquire() as tx:
            duplicates=await tx.fetchval('SELECT count(*) FROM moderation_cases WHERE target_kind=$1 AND target_id=$2',row['target_kind'],row['target_id'])
            velocity=await tx.fetchval("SELECT count(*) FROM moderation_cases WHERE reporter_id=$1 AND created_at>now()-interval '10 minutes'",row['reporter_id'])
        if duplicates>1:
            signals.append('duplicate_reports')
        if velocity>=5:
            signals.append('report_velocity')
        if row['category']=='payment_abuse':
            signals.append('reported_payment_abuse')
    record=dict(row)
    if subject and not reporter:
        # A reported party gets the decision/correction route, not reporter evidence.
        record.pop('evidence',None)
        record.pop('reporter_id',None)
    return {**record,'audit':[{k:v for k,v in dict(r).items() if reviewer or k!='actor_id'} for r in audit if reviewer or r['kind'] not in ('claim',)],
        'audit_older_available':older_available,
        'review_signals':signals,'signals_require_human_review':True,
        'can_decide':reviewer and 'moderation.decide' in p.permissions,'can_appeal':(reporter or subject) and row['status']=='decided',
        'delivery':delivery,'preserve_transaction_duties':True,
        'support_route':'/inbox','appeal_route':f'/operations/moderation?case={case_id}'}


@router.post('/cases/{case_id}/claim')
async def claim(case_id: UUID, request: Request, p=Depends(principal)):
    key,digest=operation(request,{})
    expected=revision(request)
    actor=p.actor.subject_id
    async with unit_of_work(request.app.state.pool,lock_key=f'moderation:{actor}:{key}') as tx:
        row=await case_row(tx,case_id)
        independent(row,p)
        prior=await replay(tx,actor,key,digest)
        if prior is not None:
            return prior
        check_revision(row,expected)
        if row['assigned_to'] not in (None,actor):
            raise AccessDenied('Assigned to another reviewer')
        await tx.execute("UPDATE moderation_cases SET assigned_to=$2,status=CASE WHEN status='open' THEN 'assigned' ELSE status END,revision=revision+1,updated_at=now() WHERE id=$1",case_id,actor)
        await tx.execute('INSERT INTO moderation_audit(id,case_id,actor_id,kind,reason,revision) VALUES($1,$2,$3,$4,$5,$6)',uuid4(),case_id,actor,'claim','Independent reviewer assigned',expected+1)
        return await remember(tx,actor,key,digest,{'id':str(case_id),'revision':expected+1,'status':'assigned' if row['status']=='open' else row['status']})


@router.post('/cases/{case_id}/release')
async def release(case_id: UUID, body: AssignmentRelease, request: Request, p=Depends(principal)):
    require_scope(p,'moderation.assign')
    key,digest=operation(request,body.model_dump())
    expected=revision(request)
    actor=p.actor.subject_id
    async with unit_of_work(request.app.state.pool,lock_key=f'moderation:{actor}:{key}') as tx:
        row=await case_row(tx,case_id)
        independent(row,p)
        prior=await replay(tx,actor,key,digest)
        if prior is not None:
            return prior
        check_revision(row,expected)
        if row['assigned_to'] is None:
            raise PublicError('assignment_required','The case is already awaiting a reviewer.',status=409)
        await tx.execute("""UPDATE moderation_cases SET assigned_to=NULL,
            status=CASE WHEN status='assigned' THEN 'open' ELSE status END,revision=revision+1,updated_at=now() WHERE id=$1""",case_id)
        await tx.execute('INSERT INTO moderation_audit(id,case_id,actor_id,kind,reason,revision) VALUES($1,$2,$3,$4,$5,$6)',uuid4(),case_id,actor,'release',body.reason,expected+1)
        return await remember(tx,actor,key,digest,{'id':str(case_id),'revision':expected+1,'assignment':'awaiting_independent_reviewer'})


@router.post('/cases/{case_id}/decisions')
async def decide(case_id: UUID, body: Decision, request: Request, p=Depends(principal)):
    require_scope(p,'moderation.decide')
    key,digest=operation(request,body.model_dump())
    expected=revision(request)
    actor=p.actor.subject_id
    async with unit_of_work(request.app.state.pool,lock_key=f'moderation:{actor}:{key}') as tx:
        row=await case_row(tx,case_id)
        independent(row,p)
        if row['assigned_to']!=actor:
            raise AccessDenied('Assigned reviewer required')
        prior=await replay(tx,actor,key,digest)
        if prior is not None:
            return prior
        check_revision(row,expected)
        if body.action=='suspend' and row['target_kind']!='user' or body.action=='hide' and row['target_kind']=='user':
            raise PublicError('invalid_action','Choose an action appropriate for this target.',status=422)
        event=EventEnvelope(type='trust.moderation.decided.v1',source='trust',subject=str(row['target_id']),request_id=request.state.request_id,
            data=DecisionEvent(case_id=case_id,target_kind=row['target_kind'],target_id=row['target_id'],
                action=body.action,revision=expected+1).model_dump(mode='json'))
        destination={'listing':'catalog','user':'identity','message':'communications'}[row['target_kind']]
        await enqueue(tx,event,[destination])
        await tx.execute("UPDATE moderation_cases SET status='decided',last_action=$2,last_event_id=$3,revision=revision+1,updated_at=now() WHERE id=$1",case_id,body.action,event.id)
        await tx.execute('INSERT INTO moderation_audit(id,case_id,actor_id,kind,reason,revision) VALUES($1,$2,$3,$4,$5,$6)',uuid4(),case_id,actor,body.action,body.reason,expected+1)
        return await remember(tx,actor,key,digest,{'id':str(case_id),'revision':expected+1,'status':'decided','delivery':'pending','preserve_transaction_duties':True})


@router.post('/cases/{case_id}/appeals')
async def appeal(case_id: UUID, body: Appeal, request: Request, p=Depends(principal)):
    key,digest=operation(request,body.model_dump())
    expected=revision(request)
    actor=p.actor.subject_id
    async with unit_of_work(request.app.state.pool,lock_key=f'moderation:{actor}:{key}') as tx:
        row=await case_row(tx,case_id)
        if actor not in (row['reporter_id'],row['subject_id']):
            raise AccessDenied('Case party required')
        prior=await replay(tx,actor,key,digest)
        if prior is not None:
            return prior
        check_revision(row,expected)
        if row['status']!='decided':
            raise PublicError('decision_required','A decision is required before appeal.',status=409)
        await tx.execute("UPDATE moderation_cases SET status='appealed',assigned_to=NULL,revision=revision+1,updated_at=now() WHERE id=$1",case_id)
        await tx.execute('INSERT INTO moderation_audit(id,case_id,actor_id,kind,reason,revision) VALUES($1,$2,$3,$4,$5,$6)',uuid4(),case_id,actor,'appeal',body.reason,expected+1)
        return await remember(tx,actor,key,digest,{'id':str(case_id),'revision':expected+1,'status':'appealed'})
