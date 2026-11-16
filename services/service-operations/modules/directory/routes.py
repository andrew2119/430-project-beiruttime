import asyncio
import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from .dependencies import official, principal, scoped_principal

router = APIRouter(prefix='/v1/directory', tags=['official-directory'])
Capability = Literal['maintenance', 'cleaning', 'polishing', 'repair', 'bracelet_fit', 'customization']
Purpose = Literal['servicing', 'customization']


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_revision: int = Field(ge=0, strict=True)
    capabilities: list[Capability] = Field(min_length=1, max_length=6)
    contact: str = Field(min_length=1, max_length=160)
    visit_en: str = Field(min_length=1, max_length=400)
    visit_ar: str = Field(min_length=1, max_length=400)
    scope_en: str = Field(min_length=1, max_length=600)
    scope_ar: str = Field(min_length=1, max_length=600)
    published: bool = Field(default=True, strict=True)


class Choice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    organization_id: UUID
    capability: Capability
    purpose: Purpose = 'servicing'
    expected_revision: int = Field(ge=0, strict=True)
    profile_revision: int = Field(ge=1, strict=True)


def public_profile(row, business):
    return {'organization_id': str(row['organization_id']), 'revision': row['revision'],
        'display_name': business.public_name, 'kind': business.kind, 'sample': business.sample,
        'capabilities': [item for item in row['capabilities']
            if (item == 'customization' and business.kind == 'brand' and 'customization' in business.capabilities)
            or (item != 'customization' and 'servicing' in business.capabilities)],
        **{key: row[key] for key in ('contact', 'visit_en', 'visit_ar', 'scope_en', 'scope_ar')}}


def choice_result(row):
    return {key: str(row[key]) if key in ('id', 'organization_id') else row[key]
            for key in ('id', 'organization_id', 'capability', 'purpose', 'revision', 'profile_revision')}


async def replay(tx, actor, command, key, body):
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    row = await tx.fetchrow('SELECT digest,result FROM directory_commands WHERE actor_id=$1 AND command=$2 AND key=$3', actor, command, key)
    if row:
        if row['digest'] != digest:
            raise PublicError('idempotency_conflict', 'This request key was already used.', status=409)
        return digest, json.loads(row['result'])
    return digest, None


async def record(tx, request, actor, command, key, digest, result, kind):
    await tx.execute('INSERT INTO directory_commands(actor_id,command,key,digest,result) VALUES($1,$2,$3,$4,$5::jsonb)', actor, command, key, digest, json.dumps(result))
    await enqueue(tx, EventEnvelope(type=kind, source='service-operations', subject=result.get('organization_id', str(actor)), request_id=request.state.request_id,
        data={'resource_id': result.get('id', result.get('organization_id')), 'revision': result['revision']}), ['communications'])


@router.put('/businesses/{organization_id}')
async def publish(organization_id: UUID, body: Profile, request: Request, idempotency_key: str = Header(min_length=8, max_length=100)):
    actor = await scoped_principal(request, organization_id)
    require_scope(actor, 'business.jobs.write', organization_id)
    business = await official(request, organization_id)
    if 'customization' in body.capabilities and business.kind != 'brand':
        raise PublicError('brand_required', 'Customization is available through brands only.', status=409)
    required = {'customization' if item == 'customization' else 'servicing' for item in body.capabilities}
    if not required.issubset(business.capabilities):
        raise PublicError('unsupported_service', 'The business is not onboarded for this capability.', status=409)
    command = 'publish:' + str(organization_id)
    async with unit_of_work(request.app.state.pool, lock_key='directory:' + str(organization_id)) as tx:
        digest, previous = await replay(tx, actor.actor.subject_id, command, idempotency_key, body)
        if previous is not None:
            return previous
        row = await tx.fetchrow('SELECT * FROM directory_profiles WHERE organization_id=$1 FOR UPDATE', organization_id)
        if (row['revision'] if row else 0) != body.expected_revision:
            raise PublicError('stale_revision', 'Reload the current profile before saving.', status=409)
        revision = body.expected_revision + 1
        await tx.execute('''INSERT INTO directory_profiles(organization_id,revision,capabilities,contact,visit_en,visit_ar,scope_en,scope_ar,published)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT(organization_id) DO UPDATE SET revision=$2,capabilities=$3,contact=$4,visit_en=$5,visit_ar=$6,scope_en=$7,scope_ar=$8,published=$9,updated_at=now()''',
            organization_id, revision, sorted(set(body.capabilities)), body.contact, body.visit_en, body.visit_ar, body.scope_en, body.scope_ar, body.published)
        result = {'organization_id': str(organization_id), 'revision': revision, 'published': body.published}
        await record(tx, request, actor.actor.subject_id, command, idempotency_key, digest, result, 'service.directory-published.v1')
        return result


@router.get('/businesses')
async def businesses(request: Request, purpose: Purpose = 'servicing', limit: int = Query(default=20, ge=1, le=20), after: UUID | None = None):
    # A bounded scan page carries a cursor even if fresh verification filters every row.
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch('''SELECT * FROM directory_profiles WHERE published AND ($1::uuid IS NULL OR organization_id>$1)
            AND (($2::text='customization' AND 'customization'=ANY(capabilities)) OR
                 ($2='servicing' AND EXISTS(SELECT 1 FROM unnest(capabilities) capability WHERE capability!='customization')))
            ORDER BY organization_id LIMIT $3''', after, purpose, limit + 1)
    async def verified(row):
        try:
            business = await official(request, row['organization_id'], brand_only=purpose == 'customization', capability=purpose)
        except PublicError as error:
            if error.code == 'not_official':
                return None
            raise
        return public_profile(row, business)
    items = []
    try:
        # Bounded waves fit the gateway deadline; no unbounded fan-out or N serial waits.
        async with asyncio.timeout(0.95):
            for start in range(0, min(len(rows), limit), 4):
                batch = await asyncio.gather(*(verified(row) for row in rows[start:min(start + 4, limit)]))
                items.extend(item for item in batch if item is not None)
    except TimeoutError:
        raise PublicError('unavailable', 'Business verification is temporarily unavailable.', status=503) from None
    return {'items': items, 'next_after': str(rows[limit-1]['organization_id']) if len(rows) > limit else None}


@router.get('/businesses/{organization_id}')
async def business(organization_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM directory_profiles WHERE organization_id=$1 AND published', organization_id)
    if not row:
        raise PublicError('not_found', 'Directory entry not found.', status=404)
    profile = public_profile(row, await official(request, organization_id))
    if not profile['capabilities']:
        raise PublicError('unsupported_service', 'No current directory capability is available.', status=409)
    return profile


@router.get('/providers/{organization_id}')
async def provider(organization_id: UUID, request: Request):
    # Intake consumes business eligibility only, never a watch authentication or work pass.
    profile = await business(organization_id, request)
    if not any(item != 'customization' for item in profile['capabilities']):
        raise PublicError('unsupported_service', 'A current servicing capability is required.', status=409)
    return {'organization_id': profile['organization_id'], 'official': True, 'active': True, 'kind': profile['kind']}


@router.get('/choices/current')
async def current_choice(request: Request, actor=Depends(principal)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM directory_choices WHERE actor_id=$1', actor.actor.subject_id)
    return {'choice': choice_result(row) if row else None}


@router.post('/choices')
async def choose(body: Choice, request: Request, actor=Depends(principal), idempotency_key: str = Header(min_length=8, max_length=100)):
    if 'buyer' not in actor.roles:
        raise PublicError('buyer_required', 'A buyer account is required.', status=403)
    await official(request, body.organization_id, brand_only=body.purpose == 'customization', capability=body.purpose)
    if (body.purpose == 'customization') != (body.capability == 'customization'):
        raise PublicError('invalid_scope', 'Choose a capability for the intended purpose.', status=409)
    async with unit_of_work(request.app.state.pool, lock_key='directory-choice:' + str(actor.actor.subject_id)) as tx:
        digest, previous = await replay(tx, actor.actor.subject_id, 'choose', idempotency_key, body)
        if previous is not None:
            return previous
        profile = await tx.fetchrow('SELECT * FROM directory_profiles WHERE organization_id=$1 FOR SHARE', body.organization_id)
        if not profile or not profile['published'] or body.capability not in profile['capabilities']:
            raise PublicError('unsupported_service', 'This service is not offered by this business.', status=409)
        if profile['revision'] != body.profile_revision:
            raise PublicError('stale_revision', 'Reload the current service capabilities.', status=409)
        row = await tx.fetchrow('SELECT * FROM directory_choices WHERE actor_id=$1 FOR UPDATE', actor.actor.subject_id)
        if (row['revision'] if row else 0) != body.expected_revision:
            raise PublicError('stale_revision', 'Reload your saved choice.', status=409)
        row = await tx.fetchrow('''INSERT INTO directory_choices(actor_id,id,organization_id,capability,purpose,revision,profile_revision)
            VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(actor_id) DO UPDATE SET organization_id=$3,capability=$4,purpose=$5,revision=$6,profile_revision=$7,updated_at=now() RETURNING *''',
            actor.actor.subject_id, row['id'] if row else uuid4(), body.organization_id, body.capability, body.purpose, body.expected_revision + 1, body.profile_revision)
        result = choice_result(row)
        await record(tx, request, actor.actor.subject_id, 'choose', idempotency_key, digest, result, 'service.directory-choice-saved.v1')
        return result
