"""Private command adapter. Missing current providers leave work pending."""
import asyncio
import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from bt_bulkheads import Unavailable
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.auth import require_principal
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import current_principal, require_scope
from .domain import transition


def contract():
    candidates = (Path('/opt/domain-contracts/contracts-eligibility/decisions/v1.py'),
                  Path(__file__).resolve().parents[4] / 'packages/contracts-eligibility/decisions/v1.py')
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise RuntimeError('Eligibility contract missing')
    spec = importlib.util.spec_from_file_location('eligibility_decisions_v1', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = contract()
Command, Current = schema.Command, schema.Current
router = APIRouter(prefix='/v1/eligibility-decisions')
PERMISSIONS = {'review': 'eligibility.identity.review', 'prepare': 'eligibility.grants.prepare',
               'consume': 'eligibility.grants.consume', 'revoke': 'eligibility.grants.revoke'}


async def principal(request):
    local = require_principal(request)
    token = request.headers['authorization'].split(' ', 1)[1]
    try:
        fresh = await current_principal(request.app.state.identity, token, request.state.request_id)
    except (ValidationError, ValueError):
        raise HTTPException(503) from None
    if isinstance(fresh, Unavailable):
        raise HTTPException(503)
    if str(fresh.actor.subject_id) != local.subject or fresh.actor.session_id != local.session_id:
        raise HTTPException(403)
    return fresh


def allowed(person, consent, permission):
    # Reviewers have a platform permission; business consumers need selected-business scope.
    if permission == 'eligibility.identity.review':
        require_scope(person, permission)
    else:
        require_scope(person, permission, consent['brand_id'])


async def context(request, identifier, person):
    provider = getattr(request.app.state, 'eligibility_current', None)
    if provider is None:
        return None
    try:
        async with asyncio.timeout(1.2):
            value = await provider(identifier, person.actor.subject_id, request.headers['authorization'])
        return Current.model_validate(value).model_dump(mode='json')
    except (TimeoutError, OSError, ValidationError, ValueError):
        return None


def require_current_access(current):
    if datetime.fromisoformat(current['now']) >= datetime.fromisoformat(current['expires_at']):
        raise HTTPException(403)


def envelope(body, person, consent, result, current=None):
    return {'schema_version': 'eligibility-result.v1', 'operation_id': str(body.operation_id),
            'subject_id': str(consent['buyer_id']), 'watch_id': current['watch_id'] if current else None,
            'actor_id': str(person.actor.subject_id), 'organization_id': str(consent['brand_id']),
            'expected_revision': body.expected_revision, 'pending_reason': None,
            'next_actor': None, 'next_review_at': None, **result}


@router.post('')
async def command(body: Command, request: Request):
    person = await principal(request)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    async with unit_of_work(request.app.state.pool, lock_key='eligibility-operation:' + str(body.operation_id)) as tx:
        consent = await tx.fetchrow('SELECT * FROM eligibility_consents WHERE id=$1 FOR UPDATE', body.consent_id)
        if consent is None:
            raise HTTPException(404)
        allowed(person, consent, PERMISSIONS[body.kind])
        # Current provider authorization applies to historical receipt access too.
        current = await context(request, body.consent_id, person)
        if current is None:
            # No private case identifiers leave this boundary without current case authorization.
            raise HTTPException(503)
        if (current['subject_id'] != str(consent['buyer_id'])
                or current['organization_id'] != str(consent['brand_id'])
                or current['request_id'] != str(consent['request_id'])):
            raise HTTPException(403)
        if not all(current[k] for k in ('identity_current', 'organization_current', 'assignment_current')):
            raise HTTPException(403)
        if body.kind == 'review' and current['reviewer_id'] != str(person.actor.subject_id):
            raise HTTPException(403)
        prior = await tx.fetchrow('SELECT * FROM eligibility_decision_operations WHERE operation_id=$1', body.operation_id)
        if prior:
            if prior['actor_id'] != person.actor.subject_id or prior['consent_id'] != body.consent_id or prior['digest'] != digest:
                raise HTTPException(409)
            require_current_access(current)
            return json.loads(prior['result'])
        await tx.execute('INSERT INTO eligibility_decision_states(consent_id) VALUES($1) ON CONFLICT DO NOTHING', body.consent_id)
        stored = await tx.fetchval('SELECT state FROM eligibility_decision_states WHERE consent_id=$1 FOR UPDATE', body.consent_id)
        state, result = transition(json.loads(stored), body.model_dump(mode='json'), current,
                                   str(person.actor.subject_id), dict(consent))
        result = envelope(body, person, consent, result, current)
        await tx.execute('UPDATE eligibility_decision_states SET state=$2::jsonb,revision=$3 WHERE consent_id=$1',
                         body.consent_id, json.dumps(state), state['revision'])
        await tx.execute('INSERT INTO eligibility_decision_operations(operation_id,actor_id,consent_id,digest,permission,result) VALUES($1,$2,$3,$4,$5,$6::jsonb)',
                         body.operation_id, person.actor.subject_id, body.consent_id, digest, PERMISSIONS[body.kind], json.dumps(result))
        await enqueue(tx, EventEnvelope(type='eligibility.decision-recorded.v1', source='eligibility',
            subject=str(body.consent_id), request_id=request.state.request_id,
            data={'operation_id': str(body.operation_id), 'consent_id': str(body.consent_id),
                  'revision': state['revision'], 'state': result['state']}), ['catalog', 'orders'])
        return result


@router.get('/operations/{operation_id}')
async def lookup(operation_id: UUID, request: Request):
    person = await principal(request)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM eligibility_decision_operations WHERE operation_id=$1 AND actor_id=$2',
                                operation_id, person.actor.subject_id)
        if row is None:
            raise HTTPException(404)
        consent = await tx.fetchrow('SELECT * FROM eligibility_consents WHERE id=$1', row['consent_id'])
        result = json.loads(row['result'])
        permission = row['permission']
        allowed(person, consent, permission)
        current = await context(request, row['consent_id'], person)
        if current is None:
            raise HTTPException(503)
        if (current['subject_id'] != str(consent['buyer_id']) or current['organization_id'] != str(consent['brand_id'])
                or current['request_id'] != str(consent['request_id']) or not all(current[k] for k in ('identity_current', 'organization_current', 'assignment_current'))):
            raise HTTPException(403)
        if permission == 'eligibility.identity.review' and current['reviewer_id'] != str(person.actor.subject_id):
            raise HTTPException(403)
        require_current_access(current)
        return result
