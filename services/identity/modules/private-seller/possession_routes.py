"""Private challenge routes use current authority and atomic command receipts."""
import asyncio
import json
from contextlib import asynccontextmanager
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


async def require_private_approval(tx, request, subject):
    approved = await tx.fetchval("""SELECT 1 FROM identity_private_applications
        WHERE subject_id=$1 AND status='approved' FOR SHARE""", subject)
    if not approved or request.query_params.get('organization_id') is not None:
        raise PublicError('forbidden', 'Current personal seller approval is required.', status=403)


def authority_unavailable():
    return PublicError('unavailable', 'Current listing authority is unavailable.', status=503)


@asynccontextmanager
async def possession_scope(request, listing, *, write=False):
    pool = request.app.state.pool
    provider = getattr(request.app.state, 'listing_possession_authority', None)
    native = getattr(provider, 'current_for_request', None)
    reserve = getattr(request.app.state, 'possession_command_reservation', None) if write else None
    if native is None and reserve is None:
        # The injected current() contract serializes mutations for this transaction.
        async with unit_of_work(pool) as tx:
            actor, _ = await live_actor(tx, request, lock=True)
            if provider is None:
                raise authority_unavailable()
            try:
                async with asyncio.timeout(2):
                    facts = await provider.current(str(actor['id']), str(listing))
            except (TimeoutError, OSError):
                raise authority_unavailable() from None
            authorize(str(actor['id']), facts)
            yield tx, actor, facts
        return

    async with unit_of_work(pool) as tx:
        actor, _ = await live_actor(tx, request)
        subject = actor['id']
        await require_private_approval(tx, request, subject)
    if reserve is not None:
        async with reserve(request, subject, listing) as (tx, facts):
            actor, _ = await live_actor(tx, request, lock=True)
            authorize(str(actor['id']), facts)
            await require_private_approval(tx, request, actor['id'])
            yield tx, actor, facts
        return

    # Release Identity's connection before Catalog resolves the caller.
    try:
        async with asyncio.timeout(2):
            facts = await native(request, subject, listing)
    except (TimeoutError, OSError):
        raise authority_unavailable() from None

    async with unit_of_work(pool) as tx:
        actor, _ = await live_actor(tx, request, lock=True)
        authorize(str(actor['id']), facts)
        await require_private_approval(tx, request, actor['id'])
        yield tx, actor, facts


async def storage_ready(tx):
    if not await tx.fetchval("SELECT to_regclass('identity_l19_possession_receipts') IS NOT NULL"):
        raise PublicError('unavailable', 'Private proof storage is unavailable.', status=503)


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value



async def proof_authority(tx, row, facts, listing):
    review = unpack(row['seller_review']) if row else None
    if not review:
        return facts
    permitted = await tx.fetchval("""SELECT 1 FROM identity_access_grants g
        JOIN identity_accounts a ON a.id=g.subject_id
        WHERE g.subject_id=$1 AND a.status='active' AND g.organization_id IS NULL
        AND g.revoked_at IS NULL AND 'identity.private-seller.review'=ANY(g.permissions)
        LIMIT 1 FOR SHARE OF g""", UUID(review['reviewer_id']))
    if permitted or review['verdict'] in {'correction', 'rejected'}:
        return {**facts, 'review': review, 'review_details_visible': bool(permitted)}
    if review['verdict'] == 'approved':
        active_case = await tx.fetchval("""SELECT 1 FROM identity_l19_possession_photos f
            JOIN identity_data_possession_reviews r ON r.photo_id=f.id
            WHERE f.listing_id=$1 AND f.subject_id=$2 AND f.challenge_id=$3 AND r.active_case""",
            listing, UUID(facts['subject_id']), UUID(review['challenge_id']))
        if not active_case:
            return {**facts, 'review': review, 'review_details_visible': False,
                    'approval_authority_lapsed': True}
    return facts


@router.get('/listings/{listing_id}/possession')
async def read_proof(listing_id: UUID, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    async with possession_scope(request, listing_id) as (tx, actor, facts):
        await storage_ready(tx)
        row = await tx.fetchrow('SELECT proof,seller_review FROM identity_l19_possession WHERE listing_id=$1 AND subject_id=$2', listing_id, actor['id'])
        now = await tx.fetchval('SELECT clock_timestamp()')
        return {'proof': current(unpack(row['proof']) if row else None, await proof_authority(tx, row, facts, listing_id), now)}


async def command(kind, listing, body, request):
    operation = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(operation) <= 100:
        raise PublicError('operation_key_required', 'A request key is required.', status=422)
    digest = request_digest(kind, body.model_dump(mode='json'))
    async with possession_scope(request, listing, write=True) as (tx, actor, facts):
        await storage_ready(tx)
        receipt = await tx.fetchrow('SELECT digest,result FROM identity_l19_possession_receipts WHERE subject_id=$1 AND operation_id=$2', actor['id'], operation)
        if receipt:
            result = replay({'digest': receipt['digest'], 'result': unpack(receipt['result'])}, digest, facts)
            if result['listing_id'] != str(listing):
                raise PublicError('operation_conflict', 'Use the original listing.', status=409)
            return {'proof': result}
        row = await tx.fetchrow('SELECT proof,seller_review FROM identity_l19_possession WHERE listing_id=$1 FOR UPDATE', listing)
        previous = unpack(row['proof']) if row else None
        if previous and previous['subject_id'] != str(actor['id']):
            raise PublicError('forbidden', 'Private proof belongs to its submitting seller.', status=403)
        now = await tx.fetchval('SELECT clock_timestamp()')
        photo = None
        if kind == 'issue':
            facts = await proof_authority(tx, row, facts, listing)
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
        status = await tx.execute('''INSERT INTO identity_l19_possession(listing_id,subject_id,proof)
            VALUES($1,$2,$3::jsonb)
            ON CONFLICT(listing_id) DO UPDATE SET proof=EXCLUDED.proof,seller_review=NULL
            WHERE identity_l19_possession.subject_id=EXCLUDED.subject_id''',
            listing, actor['id'], json.dumps(result))
        if status == 'INSERT 0 0':
            raise PublicError('forbidden', 'Private proof belongs to its submitting seller.', status=403)
        if photo is not None:
            await tx.execute('INSERT INTO identity_l19_possession_photos(id,listing_id,subject_id,challenge_id,content,created_at,submitted_at) VALUES($1,$2,$3,$4,$5,$6,$6)', uuid4(), listing, actor['id'], UUID(result['challenge_id']), photo, now)
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
