import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from bt_contracts.service.reduction.v1 import Authority, Command, Result
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from .domain import Rejected, authorize

router = APIRouter(prefix='/v1/reduction', tags=['reduction'])


@asynccontextmanager
async def guard(request, record_id, organization_id, kind):
    provider = getattr(request.app.state, 'reduction_authority', None)
    if provider is None:
        raise HTTPException(503, detail='unavailable')
    try:
        async with asyncio.timeout(4):
            async with provider.guard(request, record_id, organization_id, kind) as value:
                authority = Authority.model_validate(value)
                if not authority.current or authority.organization_id != organization_id:
                    raise HTTPException(403, detail='denied')
                if not authority.checked_at <= datetime.now(timezone.utc) < authority.valid_until:
                    raise HTTPException(503, detail='unavailable')
                yield authority
    except (TimeoutError, ValueError):
        raise HTTPException(503, detail='unavailable') from None


def visible(row, authority):
    if row is None or any(row[key] != getattr(authority, key) for key in ('organization_id', 'subject_id', 'watch_id')):
        raise HTTPException(403, detail='denied')


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


@router.get('/records/{record_id}')
async def detail(record_id: UUID, organization_id: UUID, request: Request):
    async with guard(request, record_id, organization_id, 'read') as authority:
        async with request.app.state.pool.acquire() as tx:
            row = await tx.fetchrow('SELECT * FROM reduction_records WHERE id=$1', record_id)
        if row is not None:
            visible(row, authority)
        return {'record': decode(row['result']) if row else None, 'context': authority.model_dump(mode='json')}


@router.get('/operations/{operation_id}')
async def lookup(operation_id: UUID, record_id: UUID, organization_id: UUID, request: Request):
    async with guard(request, record_id, organization_id, 'read') as authority:
        async with request.app.state.pool.acquire() as tx:
            row = await tx.fetchrow('SELECT * FROM reduction_records WHERE id=$1', record_id)
            if row is not None:
                visible(row, authority)
            receipt = await tx.fetchrow('SELECT * FROM reduction_operations WHERE operation_id=$1', operation_id)
        if receipt is None:
            return {'state': 'pending', 'operation_id': str(operation_id)}
        if receipt['record_id'] != record_id or receipt['actor_id'] != authority.actor_id or receipt['organization_id'] != organization_id:
            raise HTTPException(403, detail='denied')
        return decode(receipt['result'])


@router.post('/records/{record_id}/commands')
async def command(record_id: UUID, body: Command, request: Request):
    async with guard(request, record_id, body.organization_id, body.kind) as authority:
        digest = hashlib.sha256((str(record_id) + body.model_dump_json()).encode()).hexdigest()
        async with unit_of_work(request.app.state.pool, lock_key=f'reduction:{record_id}') as tx:
            prior = await tx.fetchrow('SELECT * FROM reduction_operations WHERE operation_id=$1', body.operation_id)
            if prior:
                if prior['request_hash'] != digest or prior['actor_id'] != authority.actor_id or prior['organization_id'] != body.organization_id:
                    raise HTTPException(409, detail='operation_conflict')
                result = decode(prior['result'])
                if any(result[key] != str(getattr(authority, key)) for key in ('subject_id', 'watch_id', 'organization_id')):
                    raise HTTPException(403, detail='denied')
                return result
            try:
                state = authorize(body, authority, datetime.now(timezone.utc))
            except Rejected as error:
                raise HTTPException({'denied': 403, 'stale': 409, 'unavailable': 503}[error.code], detail=error.code) from None
            row = await tx.fetchrow('SELECT * FROM reduction_records WHERE id=$1 FOR UPDATE', record_id)
            if row:
                visible(row, authority)
            if (row['revision'] if row else 0) != body.expected_revision:
                raise HTTPException(409, detail='stale')
            if body.kind == 'record':
                if row is None:
                    raise HTTPException(409, detail='stale')
                previous = decode(row['result'])
                if not set(previous['removed_link_ids']) <= {str(item) for item in body.removed_link_ids}:
                    raise HTTPException(409, detail='stale')
                original = Command.model_validate(decode(row['request']))
                for field in ('choice_id', 'target', 'recipient_id', 'subject_id', 'watch_id', 'organization_id', 'quote_id', 'quote_revision', 'policy_revision'):
                    if getattr(original, field) != getattr(body, field):
                        raise HTTPException(409, detail='stale')
            elif row is not None:
                raise HTTPException(409, detail='stale')
            revision = body.expected_revision + 1
            result = {**body.model_dump(mode='json'), 'schema_version': 'reduction.result.v1',
                'actor_id': str(authority.actor_id), 'assignment_revision': authority.assignment_revision,
                'commitment_id': str(authority.commitment_id), 'state': state, 'revision': revision,
                'accepted_exception_basis': next((item.basis for item in authority.accepted_exceptions if item.id == body.exception_id), None),
                'removed_count': len(body.removed_link_ids), 'returned_count': len(body.returned_link_ids),
                'pending_reason': 'fit_or_parts' if state == 'unresolved' else None,
                'next_actor': str(authority.responsible_actor_id), 'next_review_at': authority.next_review_at.isoformat(),
                'currency': authority.currency, 'total_minor': authority.total_minor,
                'recorded_at': datetime.now(timezone.utc).isoformat(), 'handover_authorized': False}
            result = Result.model_validate(result).model_dump(mode='json')
            payload = json.dumps(result)
            if row:
                await tx.execute('UPDATE reduction_records SET revision=$2,state=$3,result=$4::jsonb,updated_at=now() WHERE id=$1', record_id, revision, state, payload)
            else:
                await tx.execute('INSERT INTO reduction_records(id,organization_id,subject_id,watch_id,revision,state,request,result) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb)', record_id, body.organization_id, body.subject_id, body.watch_id, revision, state, body.model_dump_json(), payload)
            await tx.execute('INSERT INTO reduction_operations(operation_id,record_id,actor_id,organization_id,request_hash,result) VALUES($1,$2,$3,$4,$5,$6::jsonb)', body.operation_id, record_id, authority.actor_id, body.organization_id, digest, payload)
            await enqueue(tx, EventEnvelope(type='service-operations.reduction.recorded.v1', source='service-operations', subject=str(record_id), request_id=request.state.request_id,
                data={'record_id': str(record_id), 'revision': revision, 'state': state}), ['communications'])
            return result
