import hashlib
import json
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.responses import Response
from bt_bulkheads import Unavailable
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.auth import require_principal
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import current_principal
from bt_runtime.event_http import build_event_router

router = APIRouter(prefix='/v1/consents')


class DraftContext(BaseModel):
    # Read projection of Catalog request-drafts.v1; neutral notes/options are not retained.
    model_config = ConfigDict(extra='ignore')
    id: UUID
    brand_id: UUID | None
    kind: str
    revision: int = Field(ge=1,strict=True)
    status: str


class BrandContext(BaseModel):
    # Identity businesses.v1 is the authority for official onboarding, not a draft option.
    model_config = ConfigDict(extra='ignore')
    id: UUID
    kind: str
    state: str
    capabilities: list[str] = Field(max_length=16)
    platform_onboarded: bool = Field(strict=True)
    authenticated_business: bool = Field(strict=True)


class Consent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    brand_id: UUID
    request_revision: int = Field(ge=1,strict=True)
    purpose: str = Field(pattern=r'^brand-request-identity$')
    policy_version: str = Field(pattern=r'^demo-identity-v1$')
    decision: str = Field(pattern=r'^(agree|refuse)$')
    evidence: str | None = Field(default=None, max_length=65536)

    @field_validator('evidence')
    @classmethod
    def bounded_synthetic(cls, value):
        if value is not None and (not value.startswith('DEMO:') or not 5 <= len(value.encode()) <= 65536):
            raise ValueError('Synthetic DEMO evidence only')
        return value


class Withdraw(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1,strict=True)


async def actor(request):
    local = require_principal(request)
    token = request.headers['authorization'].split(' ',1)[1]
    try:
        fresh = await current_principal(request.app.state.identity, token, request.state.request_id)
    except (ValidationError, ValueError):
        raise HTTPException(503) from None
    if isinstance(fresh, Unavailable):
        raise HTTPException(503)
    if str(fresh.actor.subject_id) != local.subject or fresh.actor.session_id != local.session_id:
        raise HTTPException(403)
    return fresh


def view(row):
    return {key: str(row[key]) if key in {'id','buyer_id','brand_id','request_id','created_at','updated_at'} else row[key]
        for key in ('id','buyer_id','brand_id','request_id','request_revision','revision','purpose','policy_version','status','created_at','updated_at')}


def operation(request, body):
    key = request.headers.get('Idempotency-Key','')
    if not 8 <= len(key) <= 100:
        raise PublicError('operation_key_required', 'A request key is required.', status=422)
    digest = hashlib.sha256((request.url.path + body.model_dump_json()).encode()).hexdigest()
    return key, digest


async def replay(tx, buyer, key, digest):
    row = await tx.fetchrow('SELECT * FROM eligibility_consent_operations WHERE buyer_id=$1 AND key=$2', buyer, key)
    if row and row['digest'] != digest:
        raise PublicError('operation_conflict', 'Use a new request key.', status=409)
    return json.loads(row['result']) if row else None


async def record(tx, request, buyer, row, key, digest, kind, destinations):
    result = {'consent': view(row), 'effective_grant': False}
    await tx.execute('INSERT INTO eligibility_consent_operations VALUES($1,$2,$3,$4::jsonb)', buyer,key,digest,json.dumps(result))
    await tx.execute('INSERT INTO eligibility_consent_audit VALUES($1,$2,$3,$4,$5,$6,now())',uuid4(),buyer,row['id'],kind,'accepted',request.state.request_id)
    await enqueue(tx, EventEnvelope(type=kind, source='eligibility', subject=str(row['id']), request_id=request.state.request_id,
        data={'consent_id': str(row['id']), 'buyer_id':str(buyer), 'brand_id':str(row['brand_id']), 'request_id':str(row['request_id']),
            'request_revision':row['request_revision'], 'revision':row['revision'], 'status':row['status']}), destinations)
    return result


@router.get('')
async def mine(request: Request):
    principal = await actor(request)
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch('SELECT * FROM eligibility_consents WHERE buyer_id=$1 ORDER BY created_at DESC LIMIT 50', principal.actor.subject_id)
    return {'consents':[view(row) for row in rows]}


@router.post('')
async def consent(body: Consent, request: Request):
    principal = await actor(request)
    buyer = principal.actor.subject_id
    key, digest = operation(request, body)
    # Do not repeat a remote dependency for a previously acknowledged operation.
    async with request.app.state.pool.acquire() as tx:
        prior = await replay(tx,buyer,key,digest)
        if prior:
            return prior
    response = await request.app.state.catalog.request('GET', f'/v1/request-drafts/{body.request_id}',
        headers={'Authorization':request.headers['authorization'],'X-Request-ID':request.state.request_id})
    if isinstance(response, Unavailable):
        raise HTTPException(503)
    if response.status_code != 200:
        raise HTTPException(403 if response.status_code in {401,403,404} else 503)
    try:
        context = DraftContext.model_validate(response.json())
    except (ValidationError, ValueError):
        raise HTTPException(503) from None
    # The provider's owner-private GET authorizes this exact Bearer subject; no client buyer id is accepted.
    if context.id != body.request_id or context.brand_id != body.brand_id or context.revision != body.request_revision or context.status != 'draft' or context.kind != 'customization':
        raise PublicError('request_binding_changed','Reload the current brand request.',status=409)
    business = await request.app.state.identity.request('GET',f'/v1/businesses/{body.brand_id}',
        headers={'Authorization':request.headers['authorization'],'X-Request-ID':request.state.request_id})
    if isinstance(business,Unavailable) or business.status_code >= 500:
        raise HTTPException(503)
    if business.status_code != 200:
        raise PublicError('brand_unavailable','Choose a current onboarded brand for this request.',status=409)
    try:
        brand = BrandContext.model_validate(business.json())
    except (ValidationError,ValueError):
        raise HTTPException(503) from None
    if brand.id != body.brand_id or brand.kind != 'brand' or brand.state != 'active' or not brand.platform_onboarded or not brand.authenticated_business or 'customization' not in brand.capabilities:
        raise PublicError('brand_unavailable','Choose a current onboarded brand for this request.',status=409)
    if body.decision == 'agree' and body.evidence is None:
        raise PublicError('evidence_required','Provide synthetic identity evidence.',status=422)
    if body.decision == 'refuse' and body.evidence is not None:
        raise PublicError('evidence_without_consent','Remove evidence when refusing consent.',status=422)
    async with unit_of_work(request.app.state.pool,lock_key='consent-buyer:'+str(buyer)) as tx:
        prior = await replay(tx,buyer,key,digest)
        if prior:
            return prior
        exists = await tx.fetchval('''SELECT id FROM eligibility_consents WHERE buyer_id=$1 AND request_id=$2
            AND request_revision=$3 AND purpose=$4''',buyer,body.request_id,body.request_revision,body.purpose)
        if exists:
            raise PublicError('consent_already_recorded','Open the recorded consent or start a corrected request revision.',status=409)
        row = await tx.fetchrow('''INSERT INTO eligibility_consents(id,buyer_id,brand_id,request_id,request_revision,revision,purpose,policy_version,status)
            VALUES($1,$2,$3,$4,$5,1,$6,$7,$8) RETURNING *''',uuid4(),buyer,body.brand_id,body.request_id,body.request_revision,
            body.purpose,body.policy_version,'active' if body.decision=='agree' else 'refused')
        if body.evidence is not None:
            content = body.evidence.encode()
            await tx.execute('INSERT INTO eligibility_consent_evidence(id,consent_id,content,sha256) VALUES($1,$2,$3,$4)',uuid4(),row['id'],content,hashlib.sha256(content).hexdigest())
        return await record(tx,request,buyer,row,key,digest,'eligibility.consent-recorded.v1',['catalog'])


@router.post('/{consent_id}/withdraw')
async def withdraw(consent_id: UUID, body: Withdraw, request: Request):
    principal = await actor(request)
    buyer = principal.actor.subject_id
    key,digest = operation(request,body)
    async with unit_of_work(request.app.state.pool,lock_key='consent-buyer:'+str(buyer)) as tx:
        prior = await replay(tx,buyer,key,digest)
        if prior:
            return prior
        row = await tx.fetchrow('SELECT * FROM eligibility_consents WHERE id=$1 AND buyer_id=$2 FOR UPDATE',consent_id,buyer)
        if not row:
            raise HTTPException(404)
        if row['revision']!=body.expected_revision or row['status']!='active':
            raise PublicError('stale_consent','Reload the current consent.',status=409)
        row = await tx.fetchrow("UPDATE eligibility_consents SET status='withdrawal_pending',revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",consent_id)
        # Local eligibility becomes ineffective immediately. Distributed fence is still pending.
        return await record(tx,request,buyer,row,key,digest,'eligibility.consent-withdrawal-requested.v1',['catalog','orders'])


@router.get('/{consent_id}/evidence/{evidence_id}')
async def evidence(consent_id: UUID,evidence_id: UUID,request: Request):
    principal = await actor(request)
    reviewer = principal.actor.subject_id
    async with unit_of_work(request.app.state.pool,lock_key='consent:'+str(consent_id)) as tx:
        allowed = 'eligibility.identity.review' in principal.permissions and await tx.fetchval('''SELECT 1 FROM eligibility_consent_assignments a
            JOIN eligibility_consents c ON c.id=a.consent_id WHERE a.consent_id=$1 AND a.reviewer_id=$2
            AND a.revoked_at IS NULL AND c.status='active' AND c.buyer_id<>$2''',consent_id,reviewer)
        await tx.execute('INSERT INTO eligibility_consent_audit VALUES($1,$2,$3,$4,$5,$6,now())',uuid4(),reviewer,consent_id,'evidence.read','accepted' if allowed else 'denied',request.state.request_id)
        content = await tx.fetchval('SELECT content FROM eligibility_consent_evidence WHERE id=$1 AND consent_id=$2',evidence_id,consent_id) if allowed else None
    if not allowed:
        raise HTTPException(403)
    if content is None:
        raise HTTPException(404)
    return Response(content,media_type='text/plain',headers={'Content-Disposition':'attachment; filename="synthetic-proof.txt"','Cache-Control':'no-store'})


class FenceAcknowledgement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    consent_id: UUID
    revision: int = Field(ge=1,strict=True)


async def fenced(tx,event):
    try:
        acknowledgement = FenceAcknowledgement.model_validate(event.data)
    except ValidationError:
        raise HTTPException(422) from None
    identifier, revision = acknowledgement.consent_id, acknowledgement.revision
    if event.subject != str(identifier):
        raise HTTPException(409)
    row = await tx.fetchrow('SELECT * FROM eligibility_consents WHERE id=$1 FOR UPDATE',identifier)
    if not row or row['status']!='withdrawal_pending' or row['revision']!=revision:
        raise HTTPException(409)
    await tx.execute('INSERT INTO eligibility_consent_fences(consent_id,revision,source) VALUES($1,$2,$3) ON CONFLICT DO NOTHING',identifier,revision,event.source)
    count = await tx.fetchval('SELECT count(*) FROM eligibility_consent_fences WHERE consent_id=$1 AND revision=$2',identifier,revision)
    if count==2:
        await tx.execute("UPDATE eligibility_consents SET status='withdrawn',updated_at=now() WHERE id=$1",identifier)


events = build_event_router('eligibility.consent.v1',{
    'catalog.consent-fenced.v1':('catalog',fenced),
    'orders.consent-fenced.v1':('orders',fenced),
})
