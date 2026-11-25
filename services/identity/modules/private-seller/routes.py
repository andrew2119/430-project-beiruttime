"""Private application submission is not official-business onboarding or watch inspection."""
import hashlib
import json
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import Response
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.identity import live_actor
from .possession_routes import router as possession_router

router = APIRouter(prefix='/v1/private-seller')


class Application(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identity_name: str = Field(min_length=2, max_length=100)
    contact: str = Field(min_length=5, max_length=254)
    payout_reference: str = Field(pattern=r'^DEMO-[A-Za-z0-9-]{4,64}$')
    identity_evidence: str = Field(min_length=5, max_length=65536)
    possession_evidence: str = Field(min_length=5, max_length=65536)
    expected_revision: int = Field(default=0, ge=0, strict=True)

    @field_validator('identity_name', 'contact')
    @classmethod
    def meaningful_text(cls, value, info):
        if len(value.strip()) < (5 if info.field_name == 'contact' else 2):
            raise ValueError('Enter a meaningful reference')
        return value.strip()

    @field_validator('identity_evidence', 'possession_evidence')
    @classmethod
    def synthetic_only(cls, value):
        if not value.startswith('DEMO:') or len(value.encode()) > 65536:
            raise ValueError('Use bounded synthetic DEMO evidence only')
        return value


def view(row):
    return {k: str(row[k]) if k in {'id','subject_id','created_at','updated_at'} else row[k]
        for k in ('id','subject_id','revision','status','identity_name','contact','payout_reference','reason','created_at','updated_at')}


async def audit(tx, request, actor, resource, action, outcome):
    await tx.execute('INSERT INTO identity_security_audit VALUES($1,$2,$3,$4,$5,$6,now())', uuid4(), actor, resource, action, outcome, request.state.request_id)


@router.get('/applications/me')
async def mine(request: Request):
    async with unit_of_work(request.app.state.pool) as tx:
        actor, _ = await live_actor(tx, request)
        row = await tx.fetchrow('SELECT * FROM identity_private_applications WHERE subject_id=$1', actor['id'])
        return {'application': view(row) if row else None}


@router.post('/applications')
async def submit(body: Application, request: Request):
    key = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(key) <= 100:
        raise PublicError('operation_key_required', 'A request key is required.', status=422)
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    async with unit_of_work(request.app.state.pool) as tx:
        actor, _ = await live_actor(tx, request, lock=True)
        prior = await tx.fetchrow('SELECT * FROM identity_private_operations WHERE subject_id=$1 AND key=$2', actor['id'], key)
        if prior:
            if prior['digest'] != fingerprint:
                raise PublicError('operation_conflict', 'Use a new request key.', status=409)
            return json.loads(prior['result'])
        current = await tx.fetchrow('SELECT * FROM identity_private_applications WHERE subject_id=$1 FOR UPDATE', actor['id'])
        revision = current['revision'] if current else 0
        if revision != body.expected_revision or (current and current['status'] not in {'correction', 'rejected'}):
            raise PublicError('stale_application', 'Reload the current application before submitting.', status=409)
        identifier = current['id'] if current else uuid4()
        if current:
            row = await tx.fetchrow('''UPDATE identity_private_applications SET identity_name=$2,contact=$3,payout_reference=$4,
                revision=revision+1,status='pending',reason='',updated_at=now() WHERE id=$1 RETURNING *''', identifier, body.identity_name, body.contact, body.payout_reference)
        else:
            row = await tx.fetchrow('''INSERT INTO identity_private_applications(id,subject_id,revision,status,identity_name,contact,payout_reference)
                VALUES($1,$2,1,'pending',$3,$4,$5) RETURNING *''', identifier, actor['id'], body.identity_name, body.contact, body.payout_reference)
        for kind, value in [('identity',body.identity_evidence),('possession',body.possession_evidence)]:
            content = value.encode()
            await tx.execute('''INSERT INTO identity_private_evidence(id,application_id,subject_id,kind,content,sha256)
                VALUES($1,$2,$3,$4,$5,$6)''', uuid4(), identifier, actor['id'], kind, content, hashlib.sha256(content).hexdigest())
        result = {'application': view(row)}
        await tx.execute('INSERT INTO identity_private_operations VALUES($1,$2,$3,$4::jsonb)', actor['id'], key, fingerprint, json.dumps(result))
        await audit(tx, request, actor['id'], identifier, 'private-seller.submit', 'accepted')
        await enqueue(tx, EventEnvelope(type='identity.private-seller-submitted.v1', source='identity', subject=str(identifier),
            request_id=request.state.request_id, data={'application_id': str(identifier), 'revision': row['revision']}), ['communications'])
    return result


@router.get('/applications/{application_id}/evidence/{evidence_id}')
async def evidence(application_id: UUID, evidence_id: UUID, request: Request):
    async with unit_of_work(request.app.state.pool) as tx:
        actor, _ = await live_actor(tx, request, lock=True)
        case = await tx.fetchrow('SELECT subject_id FROM identity_private_applications WHERE id=$1', application_id)
        reviewer = await tx.fetchval('''SELECT 1 FROM identity_private_assignments a WHERE application_id=$1
            AND reviewer_id=$2 AND revoked_at IS NULL AND EXISTS(SELECT 1 FROM identity_access_grants g
            WHERE g.subject_id=$2 AND g.organization_id IS NULL AND g.revoked_at IS NULL
            AND 'identity.private-seller.review'=ANY(g.permissions))''', application_id, actor['id'])
        allowed = case and (case['subject_id'] == actor['id'] or (reviewer and case['subject_id'] != actor['id']))
        await audit(tx, request, actor['id'], application_id, 'private-seller.evidence', 'accepted' if allowed else 'denied')
        content = await tx.fetchval('SELECT content FROM identity_private_evidence WHERE id=$1 AND application_id=$2', evidence_id, application_id) if allowed else None
    if not allowed:
        raise HTTPException(403)
    if content is None:
        raise HTTPException(404)
    return Response(content, media_type='text/plain', headers={'Content-Disposition':'attachment; filename="synthetic-proof.txt"','Cache-Control':'no-store'})


router.include_router(possession_router)
