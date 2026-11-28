"""Admit an auction start before contacting the Orders commitment writer."""
import json
import os
from datetime import timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope


def pending():
    return PublicError('sale_mode_pending', 'The original auction start remains unconfirmed. Retry the same request.', status=503)


def receipt(auction_id, operation_id, status, code, **fields):
    return dict(auction_id=str(auction_id), operation_id=str(operation_id), status=status, code=code, **fields)


async def listing_lock(tx, listing_id):
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'listing:' + str(listing_id))


async def edit_prepared(tx, listing_id):
    return await tx.fetchval("SELECT EXISTS(SELECT 1 FROM auction_listing_edits WHERE listing_id=$1 AND state='prepared')", listing_id)


def seller_scope(principal):
    actor = principal.actor
    return actor.subject_id, actor.organization_id, actor.session_id


async def start(engine, request, command, *, key_for, fingerprint, public_lot, suspended, max_minor):
    principal = await engine.dependencies.principal(request)
    require_scope(principal, 'identity.listings.publish', principal.actor.organization_id)
    scope = seller_scope(principal)
    key = key_for(request)
    digest = fingerprint('create', command.listing_id, command)
    auction_id = uuid5(NAMESPACE_URL, f'auction:{principal.actor.subject_id}:{key}')
    pool = request.app.state.pool
    dependencies = engine.dependencies

    async def current_seller():
        current = await dependencies.principal(request)
        if seller_scope(current) != scope:
            raise AccessDenied('Current seller scope changed')
        require_scope(current, 'identity.listings.publish', scope[1])
        return current

    async def find(tx):
        row = await engine.operation(tx, principal, key, digest)
        if row is not None and row.get('auction_id') != str(auction_id) and row['status'] == 'pending':
            raise pending()
        return row

    async def save(tx, value):
        return await engine.store(tx, principal, key, digest, value, UUID(value['auction_id']))

    async def existing(tx):
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE listing_id=$1', command.listing_id)
        if lot:
            engine.owner(lot, principal)
            now = await tx.fetchval('SELECT clock_timestamp()')
            return await save(tx, receipt(lot['id'], uuid4(), 'succeeded', 'already_opened', auction=public_lot(lot, now)))

    async with unit_of_work(pool) as tx:
        intent = await find(tx)
        if intent and intent['status'] != 'pending':
            return intent
        if intent is None:
            await listing_lock(tx, command.listing_id)
            same_listing = await existing(tx)
            if same_listing:
                return same_listing
            if suspended in principal.permissions:
                return await save(tx, receipt(auction_id, uuid4(), 'denied', 'marketplace_activity_suspended'))
            if command.ends_at <= await tx.fetchval('SELECT clock_timestamp()'):
                raise PublicError('invalid_schedule', 'The auction must end in the future.', status=409)
    if intent is None:
        publication = await dependencies.listing(request, command.listing_id)
        engine.published(publication, command.listing_id, principal)
        config = int(os.environ.get('AUCTION_HIGH_VALUE_' + command.currency + '_MINOR', '1000000'))
        if not 1 <= config <= max_minor or type(publication.get('is_demo')) is not bool:
            raise PublicError('rules_unavailable', 'The auction rules or listing facts are unavailable.', status=503)
        watch = await dependencies.fence_state(request, publication['watch_id'], command.listing_id, auction_id)
        if watch['api_version'] != 2:
            raise pending()
        async with unit_of_work(pool) as tx:
            intent = await find(tx)
            if intent and intent['status'] != 'pending':
                return intent
            if intent is None:
                await listing_lock(tx, command.listing_id)
                same_listing = await existing(tx)
                if same_listing:
                    return same_listing
                if await edit_prepared(tx, command.listing_id):
                    raise PublicError('listing_edit_pending', 'Reconcile the listing edit before opening an auction.', status=409)
                await engine.require_current_publication(tx, command.listing_id, publication['revision'])
                if await tx.fetchval('''SELECT EXISTS(SELECT 1 FROM auction_operations WHERE outcome->>'status'='pending'
                        AND outcome->>'code' IN ('auction_start_pending','auction_start_release_pending','auction_start_expiry_pending')
                        AND outcome->>'listing_id'=$1)''', str(command.listing_id)):
                    raise pending()
                if watch['status'] != 'available' or watch['listing_revision'] != publication['revision']:
                    raise PublicError('sale_mode_denied', 'The watch has another sale commitment.', status=409)
                current = await current_seller()
                try:
                    await dependencies.bid_admission(request, tx, current)
                except PublicError as error:
                    if error.code != 'bid_permission_required':
                        raise
                    return await save(tx, receipt(auction_id, uuid4(), 'denied', 'marketplace_activity_suspended'))
                await current_seller()
                if command.ends_at <= await tx.fetchval('SELECT clock_timestamp()'):
                    raise PublicError('invalid_schedule', 'The auction must end in the future.', status=409)
                intent = await save(tx, receipt(auction_id, uuid4(), 'pending', 'auction_start_pending',
                    listing_id=publication['id'], listing_revision=publication['revision'], watch_id=publication['watch_id'],
                    seller_id=publication['seller_id'], is_demo=publication['is_demo'],
                    watch_revision=watch['revision'], high_value_minor=config,
                    start_deadline=command.ends_at.astimezone(timezone.utc).isoformat()))

    open_key = 'auction-open:' + str(auction_id)
    if intent['code'] == 'auction_start_pending':
        async with unit_of_work(pool) as tx:
            current = await find(tx)
            if current is None:
                raise pending()
            if current['status'] != 'pending':
                return current
            if current['code'] == 'auction_start_pending' and command.ends_at <= await tx.fetchval('SELECT clock_timestamp()'):
                current = await save(tx, dict(current, code='auction_start_expiry_pending',release_reason='schedule_ended'))
            intent = current
    if intent['code'] == 'auction_start_pending':
        remote = await dependencies.start_commitment(request, intent, principal.actor.organization_id)
        publication, watch = None, None
        if remote['status'] == 'succeeded':
            try:
                publication = await dependencies.listing(request, command.listing_id)
                watch = await dependencies.fence_state(request, intent['watch_id'], command.listing_id, auction_id)
            except (AccessDenied, PublicError):
                # A local authoritative watermark can still prove supersession.
                pass
        # The external write is already serialized by its exact retained command.
        # Recheck local publication and time, then choose one durable next phase.
        async with unit_of_work(pool) as tx:
            current = await find(tx)
            if current is None:
                raise pending()
            if current['status'] != 'pending':
                return current
            if current['code'] == 'auction_start_pending':
                operation_id = current['operation_id']
                if remote['status'] == 'denied':
                    return await save(tx, receipt(auction_id, operation_id, 'denied', 'sale_mode_denied'))
                await listing_lock(tx, command.listing_id)
                now = await tx.fetchval('SELECT clock_timestamp()')
                release_reason = await changed(engine, tx, command, current, now, publication,
                                               principal.actor.organization_id, watch)
                if release_reason is None:
                    try:
                        await current_seller()
                    except (AccessDenied, PublicError):
                        # Revocation is not evidence that Orders denied or released the
                        # original commitment. Preserve the already admitted operation.
                        raise pending() from None
                    now = await tx.fetchval('SELECT clock_timestamp()')
                    if command.ends_at <= now:
                        release_reason = 'schedule_ended'
                if release_reason is not None:
                    phase = 'auction_start_expiry_pending' if release_reason == 'schedule_ended' else 'auction_start_release_pending'
                    current = await save(tx, dict(current, code=phase, open_operation_id=remote['id'], release_reason=release_reason))
                else:
                    lot = await tx.fetchrow('''INSERT INTO auction_lots
                        (id,listing_id,watch_id,seller_id,seller_organization_id,currency,opening_minor,
                         reserve_minor,increment_bands,starts_at,ends_at,commitment_id,high_value_minor,listing_revision,
                         scheduled_ends_at,listing_is_demo)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$11,$15) RETURNING *''',
                        auction_id, command.listing_id, UUID(current['watch_id']), UUID(current['seller_id']),
                        principal.actor.organization_id, command.currency, command.opening_minor, command.reserve_minor,
                        json.dumps([band.model_dump() for band in command.increment_bands]), command.starts_at,
                        command.ends_at, str(auction_id), current['high_value_minor'], current['listing_revision'], current['is_demo'])
                    snapshot = public_lot(lot, now)
                    await enqueue(tx, EventEnvelope(type='auction.opened.v1', source='auction', subject=str(auction_id),
                        time=now, request_id=request.state.request_id, data=snapshot), ['catalog'])
                    return await save(tx, receipt(auction_id, operation_id, 'succeeded', 'auction_opened', auction=snapshot))
            intent = current
    if intent['code'] == 'auction_start_expiry_pending':
        await dependencies.expire_start_commitment(request, intent)
    elif intent['code'] == 'auction_start_release_pending':
        await dependencies.release_start_commitment(request, intent, open_key)
    else:
        raise pending()
    async with unit_of_work(pool) as tx:
        current = await find(tx)
        if current is None:
            raise pending()
        if current['status'] != 'pending':
            return current
        if (current['operation_id'], current['code'], current.get('release_reason')) != (
                intent['operation_id'], intent['code'], intent.get('release_reason')):
            raise pending()
        return await save(tx, receipt(auction_id, current['operation_id'], 'denied', current['release_reason']))


async def changed(engine, tx, command, intent, now, publication, organization, watch):
    if command.ends_at <= now:
        return 'schedule_ended'
    try:
        await engine.require_current_publication(tx, command.listing_id, intent['listing_revision'])
    except PublicError as error:
        if error.code != 'listing_changed':
            raise
        return 'listing_changed'
    if await edit_prepared(tx, command.listing_id):
        return 'listing_changed'
    if await tx.fetchval('SELECT EXISTS(SELECT 1 FROM auction_lots WHERE listing_id=$1)', command.listing_id):
        return 'listing_changed'
    if publication is None or publication['revision'] < intent['listing_revision']:
        raise pending()
    if (publication['status'] != 'published' or publication['revision'] != intent['listing_revision']
            or publication['watch_id'] != intent['watch_id'] or publication['seller_id'] != intent['seller_id']
            or publication['seller_organization_id'] != (str(organization) if organization else None)):
        return 'listing_changed'
    if (watch is None or watch['api_version'] != 2 or watch['revision'] < intent['watch_revision']+1):
        raise pending()
    if (watch['listing_revision'] != intent['listing_revision'] or watch['source_kind'] != 'auction_open'
            or watch['status'] != 'fenced' or watch['source_id'] != intent['auction_id']
            or watch['auction_committed'] or watch['revision'] != intent['watch_revision']+1):
        return 'listing_changed'
    return None
