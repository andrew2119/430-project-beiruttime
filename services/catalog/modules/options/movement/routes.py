"""Movement support is a declared review input, never a physical feasibility pass."""
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from .dependencies import official, principal, scoped_principal

router = APIRouter(prefix='/v1/options/movement', tags=['movement-options'])
def normalize_reference(value: str) -> str:
    if any(character in ',،' or ord(character) < 32 or 0x7F <= ord(character) <= 0x9F
           or 0x202A <= ord(character) <= 0x202E or 0x2066 <= ord(character) <= 0x2069 for character in value):
        raise ValueError('Use an identified reference without delimiters or control characters')
    return value


Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80), AfterValidator(normalize_reference)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Compatibility(Model):
    case: Reference
    dial: Reference
    hands: Reference
    functions: list[Reference] = Field(max_length=20)
    state: Literal['supported_for_review', 'incompatible', 'parts_unavailable']


class Option(Model):
    brand_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    label_en: str = Field(min_length=1, max_length=160)
    label_ar: str = Field(min_length=1, max_length=160)
    caliber: Reference
    cases: list[Reference] = Field(min_length=1, max_length=30)
    dials: list[Reference] = Field(min_length=1, max_length=30)
    hands: list[Reference] = Field(min_length=1, max_length=30)
    functions: list[Reference] = Field(max_length=20)
    quote_minor: int = Field(ge=0, le=999999999999, strict=True)
    currency: Literal['USD']
    compatibility_rules: list[Compatibility] = Field(default_factory=list, max_length=100)
    active: bool = Field(default=True, strict=True)


class Configuration(Model):
    case: Reference
    dial: Reference
    hands: Reference
    functions: list[Reference] = Field(max_length=20)


class Selection(Model):
    brand_id: UUID
    option_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    option_revision: int = Field(ge=1, strict=True)
    configuration: Configuration


def option_view(row):
    return {'compatibility_rules': json.loads(row['compatibility_rules']) if isinstance(row['compatibility_rules'], str) else row['compatibility_rules'], ** {key: str(row[key]) if key in ('id', 'brand_id') else row[key] for key in
        ('id', 'brand_id', 'revision', 'label_en', 'label_ar', 'caliber', 'cases', 'dials', 'hands', 'functions', 'quote_minor', 'currency')}}


def assess(option, configuration):
    reasons = []
    for singular, plural in (('case', 'cases'), ('dial', 'dials'), ('hands', 'hands')):
        if getattr(configuration, singular) not in option[plural]:
            reasons.append(singular)
    if not set(configuration.functions).issubset(option['functions']):
        reasons.append('functions')
    rules = option.get('compatibility_rules', [])
    rules = json.loads(rules) if isinstance(rules, str) else rules
    matches = [rule for rule in rules if all(rule[field] == getattr(configuration, field)
        for field in ('case', 'dial', 'hands')) and set(rule['functions']) == set(configuration.functions)]
    state = matches[0]['state'] if len(matches) == 1 and not reasons else 'manual_review'
    return {'status': state, 'unsupported': reasons,
        'physical_feasibility_pass': False, 'quote_impact': {'minor': option['quote_minor'], 'currency': option['currency'], 'indicative': True}}


async def replay(tx, actor, command, key, body):
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    row = await tx.fetchrow('SELECT digest,result FROM movement_commands WHERE actor_id=$1 AND command=$2 AND key=$3', actor, command, key)
    if row:
        if row['digest'] != digest:
            raise PublicError('idempotency_conflict', 'This request key was already used.', status=409)
        return digest, json.loads(row['result'])
    return digest, None


async def record(tx, request, actor, command, key, digest, result, kind):
    await tx.execute('INSERT INTO movement_commands VALUES($1,$2,$3,$4,$5::jsonb)', actor, command, key, digest, json.dumps(result))
    await enqueue(tx, EventEnvelope(type=kind, source='catalog', subject=result['id'], request_id=request.state.request_id,
        data={'resource_id': result['id'], 'revision': result['revision']}), ['communications'])


@router.get('/operations/{operation_id}')
async def operation(operation_id: str, command: str, request: Request, actor=Depends(principal)):
    if not 8 <= len(operation_id) <= 100 or not 1 <= len(command) <= 160:
        raise PublicError('invalid_operation', 'Use the original action reference.', status=422)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT result FROM movement_commands WHERE actor_id=$1 AND command=$2 AND key=$3', actor.actor.subject_id, command, operation_id)
    result = json.loads(row['result']) if row else None
    organization = result.get('brand_id') if result else None
    if command.startswith('publish:'):
        if not organization:
            raise PublicError('unavailable', 'Retry the original action with current business permission.', status=503)
        scoped = await scoped_principal(request, UUID(organization))
        require_scope(scoped, 'business.stock.write', UUID(organization))
        await official(request, UUID(organization), brand_only=True, capability='customization')
    elif command != 'select' or 'buyer' not in actor.roles:
        raise PublicError('forbidden', 'Current buyer permission is required.', status=403)
    archived = bool(result and (result.get('quote_impact', {}).get('currency', result.get('currency', 'USD')) != 'USD'))
    return {'schema_version': 'movement.operation.v1', 'operation_id': operation_id,
        'subject_id': str(actor.actor.subject_id), 'watch_id': None, 'actor_id': str(actor.actor.subject_id),
        'organization_id': organization, 'expected_revision': max(0, result['revision'] - 1) if result else 0,
        'state': 'saved' if result else 'pending', 'revision': result['revision'] if result else 0,
        'result': None if archived else result, 'archived': archived,
        'pending_reason': None if result else 'retry_original_reference',
        'next_actor': None if result else str(actor.actor.subject_id), 'next_review_at': None}


@router.get('')
async def options(request: Request, brand_id: UUID, limit: int = Query(default=20, ge=1, le=20), after: UUID | None = None):
    business = await official(request, brand_id, brand_only=True, capability='customization')
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch('''SELECT * FROM movement_options WHERE brand_id=$1 AND active AND currency='USD' AND ($2::uuid IS NULL OR id>$2) ORDER BY id LIMIT $3''', brand_id, after, limit + 1)
        total = await tx.fetchval("SELECT count(*) FROM movement_options WHERE brand_id=$1 AND active AND currency='USD'", brand_id)
    return {'total': total, 'items': [option_view(row) for row in rows[:limit]], 'sample': business.sample,
        'next_after': str(rows[limit-1]['id']) if len(rows) > limit else None}


@router.get('/maintenance/{brand_id}')
async def offerings(brand_id: UUID, request: Request, limit: int = Query(default=20, ge=1, le=20), after: UUID | None = None):
    actor = await scoped_principal(request, brand_id)
    require_scope(actor, 'business.stock.write', brand_id)
    await official(request, brand_id, brand_only=True, capability='customization')
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch("""SELECT * FROM movement_options WHERE brand_id=$1 AND currency='USD'
            AND ($2::uuid IS NULL OR id>$2) ORDER BY id LIMIT $3""", brand_id, after, limit + 1)
    return {'items': [{**option_view(row), 'active': row['active']} for row in rows[:limit]],
        'next_after': str(rows[limit-1]['id']) if len(rows) > limit else None}


@router.get('/{option_id}')
async def option_detail(option_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM movement_options WHERE id=$1 AND active AND currency='USD'", option_id)
    if not row:
        raise PublicError('not_found', 'This movement option is no longer published.', status=404)
    business = await official(request, row['brand_id'], brand_only=True, capability='customization')
    return {'item': option_view(row), 'sample': business.sample}


@router.put('/{option_id}')
async def publish(option_id: UUID, body: Option, request: Request, idempotency_key: str = Header(min_length=8, max_length=100)):
    actor = await scoped_principal(request, body.brand_id)
    require_scope(actor, 'business.stock.write', body.brand_id)
    await official(request, body.brand_id, brand_only=True, capability='customization')
    command = 'publish:' + str(option_id)
    async with unit_of_work(request.app.state.pool, lock_key='movement:' + str(option_id)) as tx:
        digest, previous = await replay(tx, actor.actor.subject_id, command, idempotency_key, body)
        if previous is not None:
            return previous
        row = await tx.fetchrow('SELECT * FROM movement_options WHERE id=$1 FOR UPDATE', option_id)
        if row and row['brand_id'] != body.brand_id:
            raise PublicError('forbidden', 'This movement belongs to another brand.', status=403)
        if row and row['currency'] != 'USD':
            raise PublicError('archived_currency', 'Keep the historic offering unchanged and create a separate USD offering.', status=409)
        if (row['revision'] if row else 0) != body.expected_revision:
            raise PublicError('stale_revision', 'Reload the current movement option.', status=409)
        row = await tx.fetchrow('''INSERT INTO movement_options(id,brand_id,revision,label_en,label_ar,caliber,cases,dials,hands,functions,quote_minor,currency,active,compatibility_rules)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb) ON CONFLICT(id) DO UPDATE SET revision=$3,label_en=$4,label_ar=$5,caliber=$6,cases=$7,dials=$8,hands=$9,functions=$10,quote_minor=$11,currency=$12,active=$13,compatibility_rules=$14,updated_at=now() RETURNING *''',
            option_id, body.brand_id, body.expected_revision+1, body.label_en, body.label_ar, body.caliber, body.cases, body.dials, body.hands, body.functions, body.quote_minor, body.currency, body.active, json.dumps([rule.model_dump() for rule in body.compatibility_rules]))
        result = option_view(row)
        await record(tx, request, actor.actor.subject_id, command, idempotency_key, digest, result, 'catalog.movement-published.v1')
        return result


@router.get('/selections/current')
async def current_selection(request: Request, brand_id: UUID, actor=Depends(principal)):
    if 'buyer' not in actor.roles:
        raise PublicError('buyer_required', 'Current buyer permission is required.', status=403)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT result FROM movement_selections WHERE actor_id=$1 AND brand_id=$2', actor.actor.subject_id, brand_id)
    result = json.loads(row['result']) if row else None
    archived = bool(result and result['quote_impact']['currency'] != 'USD')
    return {'selection': None if archived else result, 'archived': archived, 'selection_revision': result['revision'] if result else 0}


@router.post('/selections')
async def select(body: Selection, request: Request, actor=Depends(principal), idempotency_key: str = Header(min_length=8, max_length=100)):
    if 'buyer' not in actor.roles:
        raise PublicError('buyer_required', 'A buyer account is required.', status=403)
    await official(request, body.brand_id, brand_only=True, capability='customization')
    async with unit_of_work(request.app.state.pool, lock_key='movement-selection:' + str(actor.actor.subject_id)) as tx:
        digest, previous = await replay(tx, actor.actor.subject_id, 'select', idempotency_key, body)
        if previous is not None:
            if previous['quote_impact']['currency'] != 'USD':
                raise PublicError('archived_currency', 'Keep the historic selection unchanged and explicitly choose a current USD option.', status=409)
            return previous
        option = await tx.fetchrow("SELECT * FROM movement_options WHERE id=$1 AND brand_id=$2 AND active AND currency='USD' FOR SHARE", body.option_id, body.brand_id)
        if not option:
            raise PublicError('unsupported_movement', 'Choose a currently supported brand movement.', status=409)
        if option['revision'] != body.option_revision:
            raise PublicError('stale_revision', 'The brand has changed this movement option.', status=409)
        old = await tx.fetchrow('SELECT * FROM movement_selections WHERE actor_id=$1 AND brand_id=$2 FOR UPDATE', actor.actor.subject_id, body.brand_id)
        if (old['revision'] if old else 0) != body.expected_revision:
            raise PublicError('stale_revision', 'Reload your saved movement selection.', status=409)
        if old and json.loads(old['result'])['quote_impact']['currency'] != 'USD':
            await tx.execute('''INSERT INTO movement_selection_archive(actor_id,brand_id,revision,result)
                VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(actor_id,brand_id,revision) DO NOTHING''',
                actor.actor.subject_id, body.brand_id, old['revision'], old['result'])
        result = {'id': str(old['id'] if old else uuid4()), 'brand_id': str(body.brand_id), 'option_id': str(body.option_id), 'revision': body.expected_revision+1,
            'option_revision': body.option_revision, 'configuration': body.configuration.model_dump(), **assess(option, body.configuration)}
        await tx.execute('''INSERT INTO movement_selections(actor_id,brand_id,id,option_id,revision,option_revision,configuration,result)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb) ON CONFLICT(actor_id,brand_id) DO UPDATE SET option_id=$4,revision=$5,option_revision=$6,configuration=$7,result=$8,updated_at=now()''',
            actor.actor.subject_id, body.brand_id, UUID(result['id']), body.option_id, result['revision'], body.option_revision, body.configuration.model_dump_json(), json.dumps(result))
        await record(tx, request, actor.actor.subject_id, 'select', idempotency_key, digest, result, 'catalog.movement-selected.v1')
        return result
