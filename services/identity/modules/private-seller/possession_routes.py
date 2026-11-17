"""Private challenge routes use current authority and atomic command receipts."""
import asyncio
import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.identity import live_actor
from .possession import authorize, current, issue, submit, private_png, replay, request_digest

router = APIRouter()


class Issue(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0, strict=True)


class Submission(Issue):
    challenge_id: UUID
    code: str = Field(min_length=6, max_length=6)
    photo_base64: str = Field(min_length=1, max_length=1398104)
    synthetic_photo: bool
    safe_photo: bool


async def authority(request, actor, listing):
    provider = getattr(request.app.state, 'listing_possession_authority', None)
    if provider is None:
        raise PublicError('unavailable', 'Current listing authority is unavailable.', status=503)
    try:
        async with asyncio.timeout(2):
            result = await provider.current(str(actor), str(listing))
    except (TimeoutError, OSError):
        raise PublicError('unavailable', 'Current listing authority is unavailable.', status=503) from None
    authorize(str(actor), result)
    return result


async def storage_ready(tx):
    if not await tx.fetchval("SELECT to_regclass('identity_l19_possession_receipts') IS NOT NULL"):
        raise PublicError('unavailable', 'Private proof storage is unavailable.', status=503)


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


@router.get('/listings/{listing_id}/possession')
async def read_proof(listing_id: UUID, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    async with unit_of_work(request.app.state.pool) as tx:
        actor, _ = await live_actor(tx, request, lock=True)
        facts = await authority(request, actor['id'], listing_id)
        await storage_ready(tx)
        row = await tx.fetchrow('SELECT proof FROM identity_l19_possession WHERE listing_id=$1 AND subject_id=$2', listing_id, actor['id'])
        now = await tx.fetchval('SELECT clock_timestamp()')
        return {'proof': current(unpack(row['proof']) if row else None, facts, now)}


async def command(kind, listing, body, request):
    operation = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(operation) <= 100:
        raise PublicError('operation_key_required', 'A request key is required.', status=422)
    digest = request_digest(kind, body.model_dump(mode='json'))
    async with unit_of_work(request.app.state.pool) as tx:
        actor, _ = await live_actor(tx, request, lock=True)
        facts = await authority(request, actor['id'], listing)
        await storage_ready(tx)
        receipt = await tx.fetchrow('SELECT digest,result FROM identity_l19_possession_receipts WHERE subject_id=$1 AND operation_id=$2', actor['id'], operation)
        if receipt:
            result = replay({'digest': receipt['digest'], 'result': unpack(receipt['result'])}, digest, facts)
            if result['listing_id'] != str(listing):
                raise PublicError('operation_conflict', 'Use the original listing.', status=409)
            return {'proof': result}
        row = await tx.fetchrow('SELECT proof FROM identity_l19_possession WHERE listing_id=$1 FOR UPDATE', listing)
        previous = unpack(row['proof']) if row else None
        if previous and previous['subject_id'] != str(actor['id']):
            raise PublicError('forbidden', 'Private proof belongs to its submitting seller.', status=403)
        now = await tx.fetchval('SELECT clock_timestamp()')
        photo = None
        if kind == 'issue':
            result = issue(str(actor['id']), str(listing), facts, previous, body.expected_revision, operation, now)
        else:
            if not body.synthetic_photo or not body.safe_photo:
                raise PublicError('bad_photo', 'Declare a safe synthetic private photo.', status=422)
            result = submit(str(actor['id']), facts, previous, body.expected_revision, str(body.challenge_id), body.code, operation, now)
            try:
                async with asyncio.timeout(2):
                    photo = await asyncio.to_thread(private_png, body.photo_base64)
            except TimeoutError:
                raise PublicError('unavailable', 'Private photo processing is unavailable.', status=503) from None
        await tx.execute('''INSERT INTO identity_l19_possession(listing_id,subject_id,proof) VALUES($1,$2,$3::jsonb)
            ON CONFLICT(listing_id) DO UPDATE SET proof=EXCLUDED.proof''', listing, actor['id'], json.dumps(result))
        if photo is not None:
            await tx.execute('INSERT INTO identity_l19_possession_photos(id,listing_id,subject_id,challenge_id,content,created_at) VALUES($1,$2,$3,$4,$5,$6)', uuid4(), listing, actor['id'], UUID(result['challenge_id']), photo, now)
            await enqueue(tx, EventEnvelope(type='identity.listing-possession-submitted.v1', source='identity', subject=str(listing),
                request_id=request.state.request_id, data={'listing_id': str(listing), 'revision': result['revision']}), ['communications'])
        await tx.execute('INSERT INTO identity_l19_possession_receipts(subject_id,operation_id,digest,result) VALUES($1,$2,$3,$4::jsonb)', actor['id'], operation, digest, json.dumps(result))
        return {'proof': result}


@router.post('/listings/{listing_id}/possession/challenges')
async def challenge(listing_id: UUID, body: Issue, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await command('issue', listing_id, body, request)


@router.post('/listings/{listing_id}/possession/submissions')
async def submission(listing_id: UUID, body: Submission, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await command('submit', listing_id, body, request)
