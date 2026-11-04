"""Private evidence: scoped before byte reads, bounded, attachment-only consumers."""
import base64
import binascii
import hashlib
import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_contracts.service.intake.v1 import EvidenceUpload, IntakeEvent
from bt_contracts_core.models import EventEnvelope
from bt_contracts_core.errors import PublicError
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.files import ScopedFiles
from .dependencies import principal
from .routes import organization, operation

router=APIRouter(prefix='/v1/intake',tags=['private intake evidence'])
MAX_BYTES=262144


def bounded_content(body):
    try:
        content=base64.b64decode(body.content_base64,validate=True)
    except (ValueError,binascii.Error):
        raise PublicError('invalid_evidence','Supply a supported private file.',status=422) from None
    signatures={
        'image/jpeg':content.startswith(b'\xff\xd8\xff'),
        'image/png':content.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/webp':content.startswith(b'RIFF') and content[8:12]==b'WEBP',
        'application/pdf':content.startswith(b'%PDF-')
    }
    if not 1<=len(content)<=MAX_BYTES or not signatures[body.media_type] or (body.kind=='condition_photo' and body.media_type=='application/pdf'):
        raise PublicError('invalid_evidence','Supply a supported private file.',status=422)
    return content


@router.get('/records/{record_id}/evidence')
async def list_evidence(record_id:UUID,request:Request,p=Depends(principal)):
    org=await organization(p,request,'intake.read')
    async with request.app.state.pool.acquire() as tx:
        if not await tx.fetchval('SELECT id FROM technical_intakes WHERE id=$1 AND organization_id=$2',record_id,org):
            raise HTTPException(404)
        rows=await tx.fetch('''SELECT id,kind,media_type,octet_length(content) AS size,created_at
            FROM technical_intake_evidence WHERE record_id=$1 AND organization_id=$2 ORDER BY created_at,id LIMIT 10''',record_id,org)
    return {'items':[dict(row) for row in rows]}


@router.post('/records/{record_id}/evidence',status_code=201)
async def upload(record_id:UUID,body:EvidenceUpload,request:Request,p=Depends(principal)):
    org=await organization(p,request,'intake.write')
    actor=p.actor.subject_id
    content=bounded_content(body)
    key,digest=operation(request,body)
    raw=request.headers.get('If-Match','').strip('"')
    if not raw.isascii() or not raw.isdigit() or not 1<=len(raw)<=10:
        raise PublicError('revision_required','Reload the intake before changing it.',status=428)
    expected=int(raw)
    if expected<1:
        raise PublicError('revision_required','Reload the intake before changing it.',status=428)
    async with unit_of_work(request.app.state.pool,lock_key=f'intake:{actor}:{org}:{key}') as tx:
        prior=await tx.fetchrow('SELECT * FROM technical_intake_operations WHERE actor_id=$1 AND organization_id=$2 AND key=$3',actor,org,key)
        if prior:
            if prior['request_hash']!=digest:
                raise PublicError('idempotency_conflict','This request key has another payload.',status=409)
            return json.loads(prior['result'])
        record=await tx.fetchrow('SELECT * FROM technical_intakes WHERE id=$1 AND organization_id=$2 FOR UPDATE',record_id,org)
        if record is None:
            raise HTTPException(404)
        if record['revision']!=expected:
            raise PublicError('stale_revision','The intake changed. Reload before retrying.',status=409)
        if await tx.fetchval('SELECT count(*) FROM technical_intake_evidence WHERE record_id=$1',record_id)>=10:
            raise PublicError('evidence_limit','The private evidence limit was reached.',status=409)
        checksum=hashlib.sha256(content).hexdigest()
        if await tx.fetchval('SELECT id FROM technical_intake_evidence WHERE record_id=$1 AND kind=$2 AND sha256=$3',record_id,body.kind,checksum):
            raise PublicError('evidence_exists','This private file is already attached.',status=409)
        evidence_id=uuid4()
        rev=expected+1
        await tx.execute('''INSERT INTO technical_intake_evidence(id,record_id,organization_id,kind,media_type,content,sha256,author_id)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8)''',evidence_id,record_id,org,body.kind,body.media_type,content,checksum,actor)
        await tx.execute('UPDATE technical_intakes SET revision=$2,updated_at=now() WHERE id=$1',record_id,rev)
        await tx.execute('INSERT INTO technical_intake_audit(id,record_id,actor_id,revision,state) VALUES($1,$2,$3,$4,$5)',uuid4(),record_id,actor,rev,record['state'])
        await enqueue(tx,EventEnvelope(type='service-operations.intake.recorded.v1',source='service-operations',subject=str(record_id),request_id=request.state.request_id,
            data=IntakeEvent(record_id=record_id,order_id=record['order_id'],organization_id=org,state=record['state'],revision=rev,
                custody_receipt_id=record['custody_receipt_id']).model_dump(mode='json')),['orders','communications'])
        result={'id':str(evidence_id),'record_id':str(record_id),'revision':rev}
        await tx.execute('INSERT INTO technical_intake_operations(actor_id,organization_id,key,request_hash,result) VALUES($1,$2,$3,$4,$5::jsonb)',actor,org,key,digest,json.dumps(result))
        return result


@router.get('/evidence/{evidence_id}')
async def download(evidence_id:UUID,request:Request,p=Depends(principal)):
    org=await organization(p,request,'intake.read')
    async def authorize(principal,resource_id):
        async with request.app.state.pool.acquire() as tx:
            row=await tx.fetchrow('''SELECT e.id,e.kind,e.media_type FROM technical_intake_evidence e
                JOIN technical_intakes r ON r.id=e.record_id WHERE e.id=$1 AND e.organization_id=$2 AND r.organization_id=$2''',resource_id,org)
        if row is None:
            raise HTTPException(404)
        return row['id']
    class Store:
        async def read(self,blob_id,*,max_bytes):
            async with request.app.state.pool.acquire() as tx:
                value=await tx.fetchval('''SELECT content FROM technical_intake_evidence
                    WHERE id=$1 AND organization_id=$2 AND octet_length(content)<=$3''',blob_id,org,max_bytes)
            if value is None:
                raise HTTPException(404)
            return bytes(value)
    content=await ScopedFiles(Store(),authorize,max_bytes=MAX_BYTES).read(p,evidence_id)
    # JSON bytes require an explicit authenticated client download; no inline preview URL.
    return {'id':str(evidence_id),'content_base64':base64.b64encode(content).decode()}
