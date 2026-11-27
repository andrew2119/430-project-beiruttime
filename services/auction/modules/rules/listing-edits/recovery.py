"""V3 expiring pre-dispatch leases and independently confirmed edit recovery."""
import json
from uuid import UUID
from fastapi import APIRouter, Request
from pydantic import ValidationError
from bt_contracts.auction.core.listing_edits import PrepareListingEditV3, CommitListingEdit, EditOperationResolution
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.kernel import lock_lot, server_now
from service_app.service_auth import service
from .routes import decoded, locks, owned, watch, prepare_intent, commit_intent

router = APIRouter(prefix='/internal/v3/listing-edits')


def result(row):
    return decoded(row['commit_result'] or row['abort_result'] or row['dispatch_result'] or row['prepare_result'])


def pending(row, code):
    return {**result(row), 'status': 'pending', 'phase': 'dispatched' if row['dispatched_at'] else 'prepared', 'code': code}


async def abort_locked(tx, request, row, reason, now):
    """Caller holds operation -> listing locks; proof must already be definitive."""
    if row['state'] != 'prepared':
        return result(row)
    if row['refence_command']:
        return pending(row, 'commit_reconciliation_required')
    if reason == 'prepare_expired' and (row['protocol'] != 3 or row['dispatched_at'] is not None or now < row['expires_at']):
        return pending(row, 'dispatch_or_live_lease')
    lot = await lock_lot(tx, row['auction_id']) if row['auction_id'] else None
    if lot:
        if (lot['mode'] != 'listing_edit_pending' or lot['listing_revision'] != row['listing_revision']
                or lot['accepted_sequence'] or lot['first_bid_confirmed']):
            return pending(row, 'auction_scope_changed')
        lot = await tx.fetchrow("UPDATE auction_lots SET mode='bidding',revision=revision+1 WHERE id=$1 RETURNING *", lot['id'])
    outcome = {'operation_id': str(row['operation_id']), 'status': 'succeeded', 'phase': 'aborted', 'code': reason,
        'listing_id': str(row['listing_id']), 'watch_id': str(row['watch_id']), 'listing_revision': row['listing_revision'],
        'next_revision': row['next_revision'], 'auction_id': str(row['auction_id']) if row['auction_id'] else None,
        'auction_revision': lot['revision'] if lot else None}
    await tx.execute("""UPDATE auction_listing_edits SET state='aborted',aborted_at=$2,abort_result=$3::jsonb
        WHERE operation_id=$1""", row['operation_id'], now, json.dumps(outcome))
    await enqueue(tx, EventEnvelope(type='auction.listing-edit-aborted.v3', source='auction', subject=str(row['listing_id']),
        request_id=request.state.request_id, data={key: outcome[key] for key in
            ('operation_id', 'listing_id', 'watch_id', 'listing_revision', 'auction_id', 'auction_revision')}), ['auction-timing-v2'])
    return outcome


@router.post('/prepare')
async def prepare(body: PrepareListingEditV3, request: Request):
    service(request, {'catalog'})
    return await prepare_intent(body, request, protocol=3)


@router.post('/{operation_id}/dispatch')
async def dispatch(operation_id: UUID, request: Request):
    service(request, {'catalog'})
    async with unit_of_work(request.app.state.pool) as tx:
        row = await owned(tx, operation_id)
        await locks(tx, operation_id, row['listing_id'])
        row = await owned(tx, operation_id)
        if row['protocol'] != 3:
            raise PublicError('protocol_mismatch', 'Dispatch requires a version-three prepared lease.', status=409)
        if row['dispatch_result']:
            return decoded(row['dispatch_result'])
        if row['state'] != 'prepared':
            return result(row)
        now = await server_now(tx)
        if now >= row['expires_at']:
            return await abort_locked(tx, request, row, 'prepare_expired', now)
        outcome = {**decoded(row['prepare_result']), 'phase': 'dispatched'}
        await tx.execute("UPDATE auction_listing_edits SET dispatched_at=$2,dispatch_result=$3::jsonb,reconcile_after=$2 WHERE operation_id=$1",
                         operation_id, now, json.dumps(outcome))
        return outcome


async def expired_lease(request, operation_id):
    async with unit_of_work(request.app.state.pool) as tx:
        row = await owned(tx, operation_id)
        await locks(tx, operation_id, row['listing_id'])
        row = await owned(tx, operation_id)
        if row['state'] != 'prepared':
            return result(row)
        if row['protocol'] != 3 or row['dispatched_at'] is not None:
            return None
        now = await server_now(tx)
        if now < row['expires_at']:
            return pending(row, 'prepare_lease_active')
        return await abort_locked(tx, request, row, 'prepare_expired', now)


async def reconcile_intent(request, operation_id, *, abort_only=False):
    # Only current Catalog service wrappers or the bounded retained-intent worker
    # call this. Never invent a Catalog edit, dispatch it, or infer a denial from
    # HTTP error/404. A dispatched lease does NOT expire into permission to bid.
    early = await expired_lease(request, operation_id)
    if early:
        return early
    async with request.app.state.pool.acquire() as tx:
        row = await owned(tx, operation_id)
    deps = request.app.state.auction.dependencies
    try:
        publication = await deps.json('catalog', 'GET', f"/v1/listings/{row['listing_id']}", request)
        if (publication.get('id') != str(row['listing_id']) or publication.get('physical_watch_id') != str(row['watch_id'])
                or type(publication.get('revision')) is not int or publication.get('status') != 'published'):
            return pending(row, 'catalog_scope_changed')
        if publication['revision'] == row['next_revision']:
            if abort_only:
                return pending(row, 'commit_reconciliation_required')
            return await commit_intent(operation_id, CommitListingEdit(listing_revision=row['next_revision']), request)
        if publication['revision'] != row['listing_revision'] or row['refence_command']:
            return pending(row, 'catalog_scope_changed')
        key = row['orders_operation_key'] or str(operation_id)  # Published legacy L15 key.
        # Frozen orders-commitment/v2.1: Auction-only exact Catalog/edit read.
        # Generic operation lookup remains producer-private; no impersonation or
        # caller-submitted status is a substitute for this retained receipt.
        proof = await deps.json('orders', 'GET', f'/internal/v2/listing-edit-operations/{operation_id}?operation_key={key}',
            request, headers=deps.service_headers(request, 'orders'), missing=True)
        if proof is None:
            return pending(row, 'orders_resolution_unknown')
        try:
            proof = EditOperationResolution.model_validate(proof)
        except ValidationError:
            return pending(row, 'orders_resolution_unknown')
        if (proof.operation_key != key or proof.source_id != operation_id or proof.watch_id != row['watch_id']
                or proof.listing_id != row['listing_id'] or proof.listing_revision != row['listing_revision']
                or (row['orders_expected_revision'] is not None and proof.expected_revision != row['orders_expected_revision'])):
            return pending(row, 'orders_resolution_mismatch')
        if proof.status != 'denied':
            return pending(row, 'orders_edit_succeeded')
        current = await watch(request, row, row['listing_revision'])
        if ((row['auction_id'] is None and current.get('status') != 'available') or
                (row['auction_id'] is not None and (current.get('status') != 'fenced'
                  or current.get('source_id') != str(row['auction_id'])))):
            return pending(row, 'physical_scope_changed')
        async with unit_of_work(request.app.state.pool) as tx:
            await locks(tx, operation_id, row['listing_id'])
            row = await owned(tx, operation_id)
            return await abort_locked(tx, request, row, 'orders_denied', await server_now(tx))
    except (PublicError, AccessDenied):
        return pending(row, 'reconciliation_unavailable')


@router.post('/{operation_id}/abort')
async def abort(operation_id: UUID, request: Request):
    service(request, {'catalog'})
    return await reconcile_intent(request, operation_id, abort_only=True)


@router.post('/{operation_id}/reconcile')
async def reconcile(operation_id: UUID, request: Request):
    service(request, {'catalog'})
    return await reconcile_intent(request, operation_id)


@router.post('/{operation_id}/commit')
async def commit(operation_id: UUID, body: CommitListingEdit, request: Request):
    service(request, {'catalog'})
    return await commit_intent(operation_id, body, request)


@router.get('/{operation_id}')
async def read(operation_id: UUID, request: Request):
    service(request, {'catalog'})
    async with request.app.state.pool.acquire() as tx:
        return result(await owned(tx, operation_id))
