"""Catalog edit handshake: freeze Auction BEFORE acquiring the Orders edit fence."""
import hashlib
import json
from uuid import UUID
from datetime import timedelta
from fastapi import APIRouter, Request
from bt_contracts.auction.core.listing_edits import PrepareListingEdit, CommitListingEdit
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.kernel import lock_lot, require_bidding
from service_app.service_auth import service

router = APIRouter(prefix='/internal/v2/listing-edits')


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def binding(row, body, protocol):
    fields = ['operation_id', 'listing_id', 'watch_id', 'listing_revision', 'next_revision', 'facts_digest']
    if protocol == 3:
        fields += ['orders_operation_key', 'orders_expected_revision', 'lease_seconds']
    if row['protocol'] != protocol or any(str(row[field]) != str(getattr(body, field)) for field in fields):
        raise PublicError('idempotency_conflict', 'This edit operation has different bindings.', status=409)


async def locks(tx, operation_id, listing_id):
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'listing-edit:' + str(operation_id))
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'listing:' + str(listing_id))


async def watch(request, row, revision):
    deps = request.app.state.auction.dependencies
    result = await deps.json('orders', 'GET', f"/internal/v2/watches/{row['watch_id']}", request,
                             headers=deps.service_headers(request, 'orders'))
    if (result.get('watch_id') != str(row['watch_id']) or result.get('listing_id') != str(row['listing_id'])
            or type(result.get('revision')) is not int or result['revision'] < 1
            or type(result.get('listing_revision')) is not int or result['listing_revision'] != revision
            or type(result.get('auction_committed')) is not bool):
        raise PublicError('orders_unavailable', 'The current edit fence cannot be verified.', status=503)
    # Completed edits can retain a historical true flag on an AVAILABLE row.
    # Availability is authoritative; re-open with its exact revision CAS below.
    # A current fenced/committed auction must still never be resumed or edited.
    if result['auction_committed'] and result.get('status') != 'available':
        raise PublicError('auction_committed', 'A committed auction cannot change listing scope.', status=409)
    return result


@router.post('/prepare')
async def prepare(body: PrepareListingEdit, request: Request):
    service(request, {'catalog'})
    return await prepare_intent(body, request)


async def prepare_intent(body, request, *, protocol=2):
    async with request.app.state.pool.acquire() as tx:
        prior = await tx.fetchrow('SELECT * FROM auction_listing_edits WHERE operation_id=$1', body.operation_id)
    if prior:
        binding(prior, body, protocol)
        return decoded(prior['prepare_result'])
    # Read only to reject an already committed/legacy watch. The local mode is
    # frozen next; Catalog must then acquire Orders' serialized edit commitment.
    current = await watch(request, body.model_dump(), body.listing_revision)
    if current.get('status') not in ('available', 'fenced'):
        raise PublicError('listing_unavailable', 'The watch has another commitment.', status=409)
    if protocol == 3 and current['revision'] != body.orders_expected_revision:
        raise PublicError('stale_revision', 'Prepare the captured current Orders watch revision.', status=409)
    async with unit_of_work(request.app.state.pool) as tx:
        await locks(tx, body.operation_id, body.listing_id)
        prior = await tx.fetchrow('SELECT * FROM auction_listing_edits WHERE operation_id=$1', body.operation_id)
        if prior:
            binding(prior, body, protocol)
            return decoded(prior['prepare_result'])
        if await tx.fetchval("SELECT EXISTS(SELECT 1 FROM auction_listing_edits WHERE listing_id=$1 AND state='prepared')", body.listing_id):
            raise PublicError('listing_edit_pending', 'Another edit is awaiting reconciliation.', status=409)
        candidate = await tx.fetchrow('SELECT id FROM auction_lots WHERE listing_id=$1', body.listing_id)
        lot = await lock_lot(tx, candidate['id']) if candidate else None
        if lot:
            require_bidding(lot)
            if (lot['accepted_sequence'] or lot['first_bid_confirmed'] or lot['watch_id'] != body.watch_id
                    or lot['listing_revision'] != body.listing_revision or current.get('status') != 'fenced'
                    or current.get('source_id') != str(lot['id'])):
                raise PublicError('listing_edit_denied', 'The current auction scope cannot be edited.', status=409)
            lot = await tx.fetchrow("UPDATE auction_lots SET mode='listing_edit_pending',revision=revision+1 WHERE id=$1 RETURNING *", lot['id'])
        elif current.get('status') != 'available':
            raise PublicError('listing_edit_pending', 'Reconcile the existing auction opening first.', status=409)
        result = {'operation_id': str(body.operation_id), 'status': 'succeeded', 'phase': 'prepared',
            'listing_id': str(body.listing_id), 'watch_id': str(body.watch_id), 'listing_revision': body.listing_revision,
            'next_revision': body.next_revision, 'auction_id': str(lot['id']) if lot else None,
            'auction_revision': lot['revision'] if lot else None}
        expires = None
        if protocol == 3:
            now = await tx.fetchval('SELECT clock_timestamp()')
            expires = now + timedelta(seconds=body.lease_seconds)
            result.update(protocol=3, expires_at=expires.isoformat(), orders_operation_key=body.orders_operation_key,
                orders_expected_revision=body.orders_expected_revision)
        await tx.execute('''INSERT INTO auction_listing_edits(operation_id,listing_id,watch_id,listing_revision,
            next_revision,facts_digest,auction_id,prepare_result,protocol,orders_operation_key,orders_expected_revision,lease_seconds,expires_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13)''',
            body.operation_id, body.listing_id, body.watch_id, body.listing_revision, body.next_revision,
            body.facts_digest, lot['id'] if lot else None, json.dumps(result), protocol,
            body.orders_operation_key if protocol == 3 else None, body.orders_expected_revision if protocol == 3 else None,
            body.lease_seconds if protocol == 3 else None, expires)
        return result


async def owned(tx, operation_id):
    row = await tx.fetchrow('SELECT * FROM auction_listing_edits WHERE operation_id=$1', operation_id)
    if not row:
        raise PublicError('not_found', 'Listing edit not found.', status=404)
    return row


async def attach(request, row):
    current = await watch(request, row, row['next_revision'])
    if row['auction_id'] is None:
        if current.get('status') != 'available':
            raise PublicError('listing_edit_pending', 'Confirm the completed physical edit fence first.', status=409)
        return
    if current.get('status') == 'fenced' and current.get('source_id') == str(row['auction_id']):
        return
    if current.get('status') != 'available':
        raise PublicError('listing_edit_pending', 'The physical edit fence remains held.', status=409)
    command = decoded(row['refence_command']) if row['refence_command'] else {
        'operation_key': 'auction-edit:' + str(row['operation_id']), 'watch_id': str(row['watch_id']),
        'listing_id': str(row['listing_id']), 'listing_revision': row['next_revision'],
        'expected_revision': current['revision'], 'source_id': str(row['auction_id']), 'kind': 'auction_open',
        'reason': 'Resume the same uncommitted auction after the confirmed listing edit'}
    # Persist the exact remote command before HTTP. A 404 never means release.
    async with unit_of_work(request.app.state.pool) as tx:
        await locks(tx, row['operation_id'], row['listing_id'])
        saved = await owned(tx, row['operation_id'])
        if saved['state'] != 'prepared':
            return
        if saved['refence_command']:
            command = decoded(saved['refence_command'])
        elif saved['state'] == 'prepared':
            await tx.execute('UPDATE auction_listing_edits SET refence_command=$2::jsonb WHERE operation_id=$1',
                             row['operation_id'], json.dumps(command))
    deps = request.app.state.auction.dependencies
    remote = await deps.json('orders', 'GET', '/internal/v2/operations/' + command['operation_key'], request,
        headers=deps.service_headers(request, 'orders'), missing=True)
    if remote is None:
        remote = await deps.json('orders', 'POST', '/internal/v2/commitments', request,
            headers={**deps.service_headers(request, 'orders'), 'Idempotency-Key': command['operation_key']}, json=command)
    if remote.get('status') != 'succeeded':
        raise PublicError('listing_edit_pending', 'The auction fence is not confirmed. Resume the same edit.', status=409)
    current = await watch(request, row, row['next_revision'])
    if current.get('status') != 'fenced' or current.get('source_id') != str(row['auction_id']):
        raise PublicError('orders_unavailable', 'The resumed auction fence cannot be verified.', status=503)


@router.post('/{operation_id}/commit')
async def commit(operation_id: UUID, body: CommitListingEdit, request: Request):
    service(request, {'catalog'})
    return await commit_intent(operation_id, body, request)


async def commit_intent(operation_id, body, request):
    async with request.app.state.pool.acquire() as tx:
        row = await owned(tx, operation_id)
    if body.listing_revision != row['next_revision']:
        raise PublicError('stale_revision', 'Commit the prepared listing revision only.', status=409)
    if row['state'] == 'committed':
        return decoded(row['commit_result'])
    if row['state'] == 'aborted':
        raise PublicError('listing_edit_aborted', 'The prepared edit was definitively aborted.', status=409)
    if row['protocol'] == 3 and row['dispatched_at'] is None:
        raise PublicError('dispatch_required', 'Confirm dispatch before any physical edit command.', status=409)
    deps = request.app.state.auction.dependencies
    publication = await deps.json('catalog', 'GET', f"/v1/listings/{row['listing_id']}", request)
    try:
        actual_digest = hashlib.sha256(json.dumps(publication['facts'], sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        if (publication['id'] != str(row['listing_id']) or publication['physical_watch_id'] != str(row['watch_id'])
                or type(publication['revision']) is not int or publication['revision'] != row['next_revision']
                or publication['status'] != 'published'
                or publication['facts']['sale_mode'] not in (('auction',) if row['auction_id'] else ('auction', 'fixed_price', 'offer'))
                or actual_digest != row['facts_digest']):
            raise PublicError('listing_changed', 'Confirm the exact committed Catalog revision and facts.', status=409)
    except (KeyError, ValueError, TypeError):
        raise PublicError('catalog_unavailable', 'The committed listing cannot be verified.', status=503) from None
    await attach(request, row)
    async with unit_of_work(request.app.state.pool) as tx:
        await locks(tx, operation_id, row['listing_id'])
        row = await owned(tx, operation_id)
        if row['state'] == 'committed':
            return decoded(row['commit_result'])
        if row['state'] == 'aborted':
            raise PublicError('listing_edit_aborted', 'The prepared edit was definitively aborted.', status=409)
        lot = await lock_lot(tx, row['auction_id']) if row['auction_id'] else None
        if lot:
            if (lot['mode'] != 'listing_edit_pending' or lot['accepted_sequence'] or lot['first_bid_confirmed']
                    or lot['listing_revision'] != row['listing_revision']
                    or publication['seller_id'] != str(lot['seller_id'])
                    or publication.get('organization_id') != (str(lot['seller_organization_id']) if lot['seller_organization_id'] else None)):
                raise PublicError('listing_edit_denied', 'The current auction scope changed.', status=409)
            lot = await tx.fetchrow("""UPDATE auction_lots SET listing_revision=$2,mode='bidding',revision=revision+1
                WHERE id=$1 RETURNING *""", row['auction_id'], row['next_revision'])
            await enqueue(tx, EventEnvelope(type='auction.listing-revised.v2', source='auction', subject=str(lot['id']),
                request_id=request.state.request_id, data={'auction_id': str(lot['id']), 'listing_id': str(row['listing_id']),
                    'listing_revision': row['next_revision'], 'revision': lot['revision'], 'end_version': lot['end_version']}),
                ['auction-timing-v2'])
        result = {'operation_id': str(operation_id), 'status': 'succeeded', 'phase': 'committed',
            'listing_id': str(row['listing_id']), 'watch_id': str(row['watch_id']), 'listing_revision': row['next_revision'],
            'auction_id': str(row['auction_id']) if row['auction_id'] else None,
            'auction_revision': lot['revision'] if lot else None}
        await tx.execute("UPDATE auction_listing_edits SET state='committed',committed_at=clock_timestamp(),commit_result=$2::jsonb WHERE operation_id=$1",
                         operation_id, json.dumps(result))
        return result


@router.get('/{operation_id}')
async def read(operation_id: UUID, request: Request):
    service(request, {'catalog'})
    async with request.app.state.pool.acquire() as tx:
        row = await owned(tx, operation_id)
    return decoded(row['commit_result'] or row['abort_result'] or row['dispatch_result'] or row['prepare_result'])
