"""Persisted private possession review and serialized stock admission."""
import json
from hashlib import sha256
import secrets
import struct
import zlib
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from service_app.identity import live_actor
from .eligibility import Binding, seller_authority
from .routes import qualified_reviewer
from . import possession
from .security import require_current


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


def facts(binding):
    return possession.ListingFacts(UUID(binding['actor_id']), UUID(binding['watch_id']),
                                  binding['expected_revision'], binding['expected_revision'], True)


def restore(value):
    if value is None:
        return None
    value = dict(unpack(value))
    data = value.pop('facts')
    data['seller_id'], data['watch_id'] = UUID(data['seller_id']), UUID(data['watch_id'])
    for name in ('issued_at', 'submitted_at'):
        if value.get(name):
            value[name] = datetime.fromisoformat(value[name])
    for name in ('evidence_ref', 'reviewer_id'):
        if value.get(name):
            value[name] = UUID(value[name])
    return possession.Possession(facts=possession.ListingFacts(**data), **value)


async def fence(tx, binding):
    # Transaction locks also protect absent stock and review rows.
    for key in sorted(('listing-review:' + binding['listing_id'],
                       'listing-stock:' + binding['identity_digest'],
                       'listing-watch:' + binding['watch_id'])):
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key)


class ReviewProvider:
    async def validate(self, tx, binding):
        await fence(tx, binding)
        row = await tx.fetchrow('SELECT * FROM l02_listing_reviews WHERE listing_id=$1 FOR UPDATE', UUID(binding['listing_id']))
        old = unpack(row['binding']) if row else None
        changed = old is not None and any(old[k] != binding[k] for k in
            ('actor_id', 'organization_id', 'watch_id', 'identity_digest', 'expected_revision'))
        await tx.execute('''INSERT INTO l02_listing_reviews(listing_id,binding) VALUES($1,$2::jsonb)
            ON CONFLICT(listing_id) DO UPDATE SET binding=EXCLUDED.binding,updated_at=now()''',
            UUID(binding['listing_id']), json.dumps(binding))
        proof = restore(row['proof']) if row and not changed else None
        if changed:
            await tx.execute('UPDATE l02_listing_reviews SET proof=NULL,photo=NULL,stock_clearance=NULL WHERE listing_id=$1', UUID(binding['listing_id']))
        duplicate = await tx.fetchval('''SELECT listing_id FROM l02_listing_stock
            WHERE (identity_digest=$1 OR watch_id=$2) AND listing_id<>$3 FOR UPDATE''',
            binding['identity_digest'], UUID(binding['watch_id']), UUID(binding['listing_id']))
        same_watch = await tx.fetchval('''SELECT listing_id FROM l02_listing_stock
            WHERE watch_id=$1 AND listing_id<>$2 LIMIT 1 FOR UPDATE''',
            UUID(binding['watch_id']), UUID(binding['listing_id']))
        clearance = unpack(row['stock_clearance']) if row and not changed and row.get('stock_clearance') else None
        matches = sorted(str(item['listing_id']) for item in await tx.fetch(
            'SELECT listing_id FROM l02_listing_stock WHERE identity_digest=$1 AND listing_id<>$2',
            binding['identity_digest'], UUID(binding['listing_id'])))
        resolved = clearance and clearance.get('matches') == matches
        denied = same_watch or (resolved and clearance['verdict'] == 'duplicate')
        ambiguous = duplicate and not (resolved and clearance['verdict'] == 'distinct')
        state = 'denied' if denied or changed else 'pending'
        approved = binding['organization_id'] is not None or possession.publication_allowed(proof, facts(binding))
        if not denied and not ambiguous and not changed and approved:
            state = 'eligible'
            await tx.execute('''INSERT INTO l02_listing_stock VALUES($1,$2,$3)
                ON CONFLICT DO NOTHING''', binding['identity_digest'], UUID(binding['watch_id']), UUID(binding['listing_id']))
        result = dict(binding, state=state, revision=proof.revision if proof else 1, current=True,
                      duplicate_review='denied' if denied else ('clear' if state == 'eligible' else 'required'),
                      pending_reason='listing_review_required' if state == 'pending' else None,
                      next_actor='assigned_reviewer' if state == 'pending' else None,
                      next_review_at=datetime.now(timezone.utc) + timedelta(hours=24) if state == 'pending' else None)
        if state == 'eligible' and proof:
            result.update(proof_listing_id=binding['listing_id'], proof_watch_id=binding['watch_id'],
                proof_identity_digest=binding['identity_digest'], proof_revision=proof.revision,
                code_issued_at=proof.issued_at, proof_submitted_at=proof.submitted_at,
                single_use_code_consumed=True, reviewed=True)
        return result


@asynccontextmanager
async def lifespan(app):
    app.state.listing_eligibility_review = ReviewProvider()
    yield


router = APIRouter(prefix='/v1/listing-reviews', lifespan=lifespan)


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    challenge_id: UUID | None = None
    code: str | None = Field(default=None, pattern=r'^\d{6}$')
    reviewer_id: UUID | None = None
    assignment_revision: int = Field(default=0, ge=0)
    verdict: str | None = None
    reason: str = Field(default='', max_length=500)


async def command(listing_id, body, request, action, photo=None):
    async with unit_of_work(request.app.state.pool) as tx:
        account, _ = await live_actor(tx, request, lock=True)
        actor = account['id']
        row = await tx.fetchrow('SELECT * FROM l02_listing_reviews WHERE listing_id=$1', listing_id)
        if not row:
            raise PublicError('review_required', 'Request publication before submitting proof.', status=409)
        binding = unpack(row['binding'])
        await fence(tx, binding)
        row = await tx.fetchrow('SELECT * FROM l02_listing_reviews WHERE listing_id=$1 FOR UPDATE', listing_id)
        binding = unpack(row['binding'])
        allowed, _ = await seller_authority(tx, Binding.model_validate(binding))
        if not allowed or binding['organization_id'] is not None:
            raise AccessDenied('Current private seller required')
        if action in {'issue', 'submit'} and str(actor) != binding['actor_id']:
            raise AccessDenied('Listing owner required')
        if action in {'assign', 'decide'}:
            await require_current(tx, request, 'identity.private-seller.assign' if action == 'assign'
                                  else 'identity.private-seller.review', actor)
        operation = request.headers.get('Idempotency-Key', '')
        if not 8 <= len(operation) <= 128:
            raise PublicError('operation_key_required', 'A request key is required.', status=422)
        fingerprint = sha256((str(listing_id) + action + body.model_dump_json()).encode()).hexdigest()
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'listing-operation:' + str(actor) + ':' + operation)
        receipt = await tx.fetchrow('SELECT * FROM l02_listing_review_receipts WHERE actor_id=$1 AND operation_id=$2', actor, operation)
        if receipt:
            if receipt['fingerprint'] != fingerprint:
                raise PublicError('idempotency_conflict', 'Use the original request.', status=409)
            return unpack(receipt['result'])
        proof = restore(row['proof'])
        current = facts(binding)
        now = await tx.fetchval('SELECT clock_timestamp()')
        challenge, code = body.challenge_id, body.code
        try:
            if action == 'issue':
                if body.revision != (proof.revision if proof else 0):
                    raise possession.PossessionDenied('stale_revision')
                challenge, code = uuid4(), f'{secrets.randbelow(1000000):06d}'
                proof = possession.issue(current, actor, challenge, code, now, existing=proof)
            elif action == 'submit':
                if not proof or not photo or not challenge or not code:
                    raise possession.PossessionDenied('private_evidence_required')
                proof = possession.submit(proof, current, actor, body.revision, challenge, code,
                                          uuid4(), now, evidence_owned=True)
            else:
                permission = 'identity.private-seller.assign' if action == 'assign' else 'identity.private-seller.review'
                await require_current(tx, request, permission, actor)
                if not proof:
                    raise possession.PossessionDenied('pending_review_required')
                if action == 'assign':
                    await qualified_reviewer(tx, body.reviewer_id, current.seller_id)
                    proof = possession.assign(proof, current, body.revision, body.reviewer_id,
                                              operator_permitted=True, reviewer_qualified=True)
                else:
                    proof = possession.decide(proof, current, actor, body.revision, body.assignment_revision,
                                              body.verdict, body.reason, reviewer_qualified=True)
        except possession.PossessionDenied as error:
            raise PublicError(str(error), 'Reload the current private proof.', status=409) from None
        await tx.execute('UPDATE l02_listing_reviews SET proof=$2::jsonb,photo=coalesce($3,photo) WHERE listing_id=$1',
                         listing_id, json.dumps(asdict(proof), default=str), photo)
        await tx.execute('INSERT INTO l02_listing_review_audit(listing_id,actor_id,action,revision) VALUES($1,$2,$3,$4)',
                         listing_id, actor, action, proof.revision)
        result = dict(revision=proof.revision, state=proof.state, assignment_revision=proof.assignment_revision)
        if action == 'issue':
            result.update(challenge_id=str(challenge), code=code)
        await tx.execute('INSERT INTO l02_listing_review_receipts VALUES($1,$2,$3,$4::jsonb)',
                         actor, operation, fingerprint, json.dumps(result))
        return result


@router.post('/{listing_id}/challenges')
async def issue(listing_id: UUID, body: Command, request: Request):
    return await command(listing_id, body, request, 'issue')


class Submission(Command):
    photo_base64: str = Field(max_length=2800000)


@router.post('/{listing_id}/submissions')
async def submit(listing_id: UUID, body: Submission, request: Request):
    import base64
    import binascii
    try:
        photo = base64.b64decode(body.photo_base64, validate=True)
    except (ValueError, binascii.Error):
        raise PublicError('invalid_photo', 'Submit a private watch photo.', status=422) from None
    if not photo.startswith(b'\x89PNG\r\n\x1a\n') or len(photo) > 2 * 1024 * 1024:
        raise PublicError('invalid_photo', 'Submit a private watch photo.', status=422)
    try:
        validate_png(photo)
    except (ValueError, zlib.error, struct.error):
        raise PublicError('invalid_photo', 'Submit a private watch photo.', status=422) from None
    return await command(listing_id, body, request, 'submit', photo)


@router.post('/{listing_id}/assignment')
async def assign(listing_id: UUID, body: Command, request: Request):
    return await command(listing_id, body, request, 'assign')


@router.post('/{listing_id}/decision')
async def decide(listing_id: UUID, body: Command, request: Request):
    return await command(listing_id, body, request, 'decide')


@router.get('/{listing_id}/photo')
async def photo(listing_id: UUID, request: Request):
    async with unit_of_work(request.app.state.pool) as tx:
        actor, _ = await live_actor(tx, request, lock=True)
        await require_current(tx, request, 'identity.private-seller.review', actor['id'])
        row = await tx.fetchrow('SELECT * FROM l02_listing_reviews WHERE listing_id=$1 FOR SHARE', listing_id)
        if not row or not row['proof']:
            raise AccessDenied('Current assignment required')
        proof = restore(row['proof'])
        try:
            possession.read_evidence(proof, facts(unpack(row['binding'])), actor['id'], reviewer_qualified=True)
        except possession.PossessionDenied:
            raise AccessDenied('Current assignment required') from None
        await tx.execute('INSERT INTO l02_listing_review_audit(listing_id,actor_id,action,revision) VALUES($1,$2,$3,$4)',
                         listing_id, actor['id'], 'photo_read', proof.revision)
        return Response(bytes(row['photo']), media_type='image/png', headers={'Cache-Control': 'no-store'})


@router.get('/{listing_id}')
async def status(listing_id: UUID, request: Request):
    async with unit_of_work(request.app.state.pool) as tx:
        actor, _ = await live_actor(tx, request, lock=True)
        row = await tx.fetchrow('SELECT * FROM l02_listing_reviews WHERE listing_id=$1 FOR SHARE', listing_id)
        if not row or unpack(row['binding'])['actor_id'] != str(actor['id']):
            raise AccessDenied('Listing owner required')
        proof = restore(row['proof'])
        return dict(state=proof.state if proof else 'required', revision=proof.revision if proof else 0,
                    assignment_revision=proof.assignment_revision if proof else 0)


def validate_png(photo):
    """Validate bounded, nonanimated PNG data without optional dependencies."""
    offset, compressed, header, ended = 8, bytearray(), None, False
    while offset < len(photo):
        length = struct.unpack('>I', photo[offset:offset + 4])[0]
        kind = photo[offset + 4:offset + 8]
        data = photo[offset + 8:offset + 8 + length]
        crc = photo[offset + 8 + length:offset + 12 + length]
        if len(crc) != 4 or zlib.crc32(kind + data) != struct.unpack('>I', crc)[0]:
            raise ValueError('invalid_photo')
        if header is None:
            if kind != b'IHDR' or length != 13:
                raise ValueError('invalid_photo')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', data)
            if not 0 < width * height <= 4000000 or not width or not height or depth != 8 or color not in (0, 2, 4, 6) or compression or filtering or interlace:
                raise ValueError('invalid_photo')
            header = (width, height, {0: 1, 2: 3, 4: 2, 6: 4}[color])
        elif kind == b'IDAT':
            compressed.extend(data)
        elif kind == b'IEND':
            ended = length == 0 and offset + 12 == len(photo)
            break
        elif kind == b'acTL' or kind[:1].isupper():
            raise ValueError('invalid_photo')
        offset += length + 12
    if not header or not ended:
        raise ValueError('invalid_photo')
    width, height, channels = header
    size = height * (1 + width * channels)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, size + 1)
    if len(raw) != size or not decoder.eof or decoder.unused_data or any(raw[i] > 4 for i in range(0, size, 1 + width * channels)):
        raise ValueError('invalid_photo')


class StockDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    verdict: str = Field(pattern='^(distinct|duplicate)$')
    reason: str = Field(min_length=5, max_length=500)


@router.post('/{listing_id}/stock-decision')
async def stock_decision(listing_id: UUID, body: StockDecision, request: Request):
    async with unit_of_work(request.app.state.pool) as tx:
        account, _ = await live_actor(tx, request, lock=True)
        actor = account['id']
        await require_current(tx, request, 'identity.private-seller.review', actor)
        row = await tx.fetchrow('SELECT * FROM l02_listing_reviews WHERE listing_id=$1', listing_id)
        if not row:
            raise AccessDenied('Current review required')
        binding = unpack(row['binding'])
        await fence(tx, binding)
        row = await tx.fetchrow('SELECT * FROM l02_listing_reviews WHERE listing_id=$1 FOR UPDATE', listing_id)
        if unpack(row['binding']) != binding:
            raise PublicError('stale_revision', 'Reload the current review.', status=409)
        await qualified_reviewer(tx, actor, UUID(binding['actor_id']))
        if body.revision != binding['expected_revision']:
            raise PublicError('stale_revision', 'Reload the current review.', status=409)
        operation = request.headers.get('Idempotency-Key', '')
        if not 8 <= len(operation) <= 128:
            raise PublicError('operation_key_required', 'A request key is required.', status=422)
        fingerprint = sha256((str(listing_id) + 'stock-decision' + body.model_dump_json()).encode()).hexdigest()
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'listing-operation:' + str(actor) + ':' + operation)
        receipt = await tx.fetchrow('SELECT * FROM l02_listing_review_receipts WHERE actor_id=$1 AND operation_id=$2', actor, operation)
        if receipt:
            if receipt['fingerprint'] != fingerprint:
                raise PublicError('idempotency_conflict', 'Use the original request.', status=409)
            return unpack(receipt['result'])
        matches = sorted(str(item['listing_id']) for item in await tx.fetch(
            'SELECT listing_id FROM l02_listing_stock WHERE identity_digest=$1 AND listing_id<>$2',
            binding['identity_digest'], listing_id))
        clearance = dict(matches=matches, verdict=body.verdict, reason=body.reason, reviewer_id=str(actor))
        await tx.execute('UPDATE l02_listing_reviews SET stock_clearance=$2::jsonb WHERE listing_id=$1', listing_id, json.dumps(clearance))
        await tx.execute('INSERT INTO l02_listing_review_audit(listing_id,actor_id,action,revision) VALUES($1,$2,$3,$4)', listing_id, actor, 'stock_' + body.verdict, body.revision)
        result = dict(state=body.verdict, revision=body.revision)
        await tx.execute('INSERT INTO l02_listing_review_receipts VALUES($1,$2,$3,$4::jsonb)', actor, operation, fingerprint, json.dumps(result))
        return result
