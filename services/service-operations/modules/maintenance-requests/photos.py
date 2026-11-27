"""Private photo storage, attachment and expiration."""
import asyncio
import hashlib
from uuid import uuid4

from asyncpg import InterfaceError, PostgresError

from bt_contracts.service.intake.private_image import strip_metadata
from bt_contracts.service.maintenance.v1 import unsubmitted_photo_expires_at
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work


def operation_lock(operation_id):
    return f'maintenance:{operation_id}'


def photo_scope(command):
    return (command.brand_id, command.intervention, command.watch_revision,
            command.capability_revision, command.policy_revision)


async def store_photo(tx, actor_id, body, content):
    binding = (body.request_operation_id, actor_id, body.organization_id)
    existing = await tx.fetchrow(
        '''SELECT photo_ref, request_hash, request_id, content IS NOT NULL AS available, expires_at
           FROM maintenance_request_photos WHERE request_operation_id=$1 AND actor_id=$2
           AND organization_id=$3 AND upload_operation_id=$4 FOR UPDATE''',
        *binding, body.operation_id)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    if existing:
        if existing['request_hash'] != digest:
            raise PublicError('operation_conflict', 'The upload reference has another payload.', status=409)
        now = await tx.fetchval('SELECT clock_timestamp()')
        if not existing['available'] or (existing['request_id'] is None and now >= existing['expires_at']):
            raise PublicError('photo_expired', 'Select the photo again for a new request.', status=409)
        return existing['photo_ref']

    if await tx.fetchval('''SELECT 1 FROM maintenance_closed_operations
            WHERE operation_id=$1 AND actor_id=$2 AND organization_id=$3''', *binding):
        raise PublicError('operation_conflict', 'The request operation is closed.', status=409)
    if await tx.fetchval('SELECT 1 FROM maintenance_request_operations WHERE operation_id=$1', body.request_operation_id):
        raise PublicError('operation_conflict', 'The request operation already resolved.', status=409)
    count = await tx.fetchval('''SELECT count(*) FROM maintenance_request_photos
        WHERE request_operation_id=$1 AND actor_id=$2 AND organization_id=$3''', *binding)
    if count >= 100:
        raise PublicError('photo_limit', 'This request has reached its private photo limit.', status=409)

    clean = await asyncio.to_thread(strip_metadata, content, body.media_type, body.safe_photo_declared)
    now = await tx.fetchval('SELECT clock_timestamp()')
    reference = uuid4()
    await tx.execute('''INSERT INTO maintenance_request_photos (
        request_operation_id, actor_id, organization_id, upload_operation_id, watch_id,
        photo_ref, request_hash, media_type, content, uploaded_at, expires_at,
        brand_id, intervention, watch_revision, capability_revision, policy_revision
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)''',
        *binding, body.operation_id, body.watch_id, reference, digest, body.media_type,
        clean, now, unsubmitted_photo_expires_at(now), *photo_scope(body))
    return reference


async def attach(tx, command, request_id):
    rows = await tx.fetch('''SELECT photo_ref, expires_at FROM maintenance_request_photos
        WHERE photo_ref=ANY($1::uuid[]) AND actor_id=$2 AND organization_id=$3
        AND watch_id=$4 AND request_operation_id=$5 AND request_id IS NULL AND content IS NOT NULL
        AND (brand_id, intervention, watch_revision, capability_revision, policy_revision)
            = ($6,$7,$8,$9,$10)
        ORDER BY photo_ref FOR UPDATE''', command.photo_refs, command.actor_id,
        command.organization_id, command.watch_id, command.operation_id, *photo_scope(command))
    now = await tx.fetchval('SELECT clock_timestamp()')
    if len(rows) != len(command.photo_refs) or any(row['expires_at'] <= now for row in rows):
        return False
    await tx.execute('UPDATE maintenance_request_photos SET request_id=$1 WHERE photo_ref=ANY($2::uuid[])',
                     request_id, command.photo_refs)
    return True


async def discard_unattached(tx, operation_id, actor_id, organization_id):
    await tx.execute('''UPDATE maintenance_request_photos SET content=NULL
        WHERE request_operation_id=$1 AND actor_id=$2 AND organization_id=$3
        AND request_id IS NULL AND content IS NOT NULL''', operation_id, actor_id, organization_id)


async def expire_batch(tx):
    await tx.execute('''WITH expired AS (
        SELECT photo_ref FROM maintenance_request_photos
        WHERE request_id IS NULL AND content IS NOT NULL AND expires_at <= statement_timestamp()
        ORDER BY expires_at, photo_ref LIMIT 100 FOR UPDATE SKIP LOCKED
    )
    UPDATE maintenance_request_photos p SET content=NULL FROM expired
    WHERE p.photo_ref=expired.photo_ref''')


async def run_expiry(app, stop):
    while not stop.is_set():
        delay = 60
        try:
            async with unit_of_work(app.state.pool) as tx:
                await expire_batch(tx)
        except (OSError, InterfaceError, PostgresError):
            delay = 3
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass
