import asyncio
import importlib.util
import json
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from asyncpg import PostgresError


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    import bt_contracts.service.fit_measurement.v1 as _contract
except ModuleNotFoundError as error:
    if error.name not in ('bt_contracts', 'bt_contracts.service', 'bt_contracts.service.fit_measurement',
                          'bt_contracts.service.fit_measurement.v1'):
        raise
    _leaf = 'packages/contracts-service/fit-measurement/v1.py'
    _source = next((parent / _leaf for parent in Path(__file__).resolve().parents if (parent / _leaf).is_file()), None)
    if _source is None:
        raise RuntimeError('Fit measurement contract unavailable') from error
    _contract = load('fit_measurement_contract', _source)
_model = load('fit_measurement_model', Path(__file__).with_name('model.py'))
router = APIRouter(prefix='/v1/fit-measurement', tags=['fit measurement'])


async def authority(request, tx, subject, watch, organization):
    provider = getattr(request.app.state, 'fit_measurement_authority', None)
    if provider is None:
        raise HTTPException(503, detail='unavailable')
    try:
        async with asyncio.timeout(1.2):
            # The provider retains the current scope fence through transaction commit.
            actor, proof = await provider(request, tx, subject, watch, organization)
        if not isinstance(actor, UUID):
            raise HTTPException(503, detail='unavailable')
        return actor, proof
    except (TimeoutError, ConnectionError):
        raise HTTPException(503, detail='unavailable') from None


def database(request):
    pool = getattr(request.app.state, 'pool', None)
    if pool is None:
        raise HTTPException(503, detail='unavailable')
    return pool


async def lock(tx, key):
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key)


@router.get('/context')
async def context(request: Request, subject_id: UUID, watch_id: UUID, organization_id: UUID):
    try:
        async with database(request).acquire(timeout=1.2) as tx, tx.transaction():
            await tx.execute("SET LOCAL statement_timeout = '2000ms'")
            actor, proof = await authority(request, tx, subject_id, watch_id, organization_id)
            source = proof.get('source_revision') if isinstance(proof, dict) else None
            if type(source) is not int or source < 1:
                raise HTTPException(503, detail='unavailable')
            from types import SimpleNamespace
            scope = SimpleNamespace(subject_id=subject_id, watch_id=watch_id, organization_id=organization_id, source_revision=source)
            try:
                _model.require_authority(proof, actor, scope, buyer_only=False)
            except _model.Rejected as error:
                raise HTTPException(error.status, detail=error.code) from None
            row = await tx.fetchrow('SELECT result FROM l25_fit_records WHERE subject_id=$1 AND watch_id=$2 AND organization_id=$3', subject_id, watch_id, organization_id)
            result = row['result'] if row else None
            return {'subject_id': str(subject_id), 'watch_id': str(watch_id), 'organization_id': str(organization_id),
                    'source_revision': source, 'record': json.loads(result) if isinstance(result, str) else result}
    except (PostgresError, ConnectionError, TimeoutError):
        raise HTTPException(503, detail='unavailable') from None



@router.post('/records')
async def record(request: Request):
    raw = bytearray()
    try:
        async with asyncio.timeout(4):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 2048:
                    raise HTTPException(413, detail='request_too_large')
                raw.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, detail='request_timeout') from None
    try:
        body = _contract.Command.model_validate_json(raw)
        mm = _contract.millimeters(body.circumference, body.unit)
    except ValueError:
        raise HTTPException(422, detail='invalid_measurement') from None
    try:
        async with database(request).acquire(timeout=1.2) as tx, tx.transaction():
            await tx.execute("SET LOCAL lock_timeout = '1200ms'")
            await tx.execute("SET LOCAL statement_timeout = '2000ms'")
            await lock(tx, 'fit-operation:' + str(body.operation_id))
            await lock(tx, f'fit-record:{body.subject_id}:{body.watch_id}:{body.organization_id}')
            actor, proof = await authority(request, tx, body.subject_id, body.watch_id, body.organization_id)
            prior = await tx.fetchrow('SELECT * FROM l25_fit_operations WHERE operation_id=$1', body.operation_id)
            current = await tx.fetchrow('SELECT revision FROM l25_fit_records WHERE subject_id=$1 AND watch_id=$2 AND organization_id=$3', body.subject_id, body.watch_id, body.organization_id)
            result = _model.resolve(body, actor, proof, prior, current, mm)
            if prior:
                return result
            encoded = json.dumps(result)
            await tx.execute('''INSERT INTO l25_fit_records(subject_id,watch_id,organization_id,revision,result)
                VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT(subject_id,watch_id,organization_id)
                DO UPDATE SET revision=EXCLUDED.revision,result=EXCLUDED.result''', body.subject_id, body.watch_id, body.organization_id, result['revision'], encoded)
            await tx.execute('INSERT INTO l25_fit_operations VALUES($1,$2,$3,$4,$5::jsonb)', body.operation_id, actor, body.organization_id, _model.digest(body), encoded)
            await tx.execute('INSERT INTO l25_fit_outbox(operation_id,subject_id,watch_id,organization_id,revision) VALUES($1,$2,$3,$4,$5)', body.operation_id, body.subject_id, body.watch_id, body.organization_id, result['revision'])
            return result
    except _model.Rejected as error:
        raise HTTPException(error.status, detail=error.code) from None

    except (PostgresError, ConnectionError, TimeoutError):
        raise HTTPException(503, detail='unavailable') from None
