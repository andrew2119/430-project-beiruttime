"""Recoverable Orders first-bid commitment, using the canonical operation ledger.

No network call holds an aggregate lock. Reconciliation precedes fresh fee
validation: an expired preview cannot strand a known remote fence forever.
"""
import json
from uuid import uuid4
from fastapi import HTTPException
from bt_contracts_core.errors import PublicError, AccessDenied
from bt_contracts.auction.core.models import next_minimum
from bt_runtime.app.db import unit_of_work
from .kernel import lock_lot, require_bidding, server_now


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


async def operation(tx, principal, key, digest, auction_id):
    # The SAME order as canonical submit/create: operation -> auction.
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                     f'operation:{principal.actor.subject_id}:{key}')
    row = await tx.fetchrow('SELECT * FROM auction_operations WHERE subject_id=$1 AND operation_key=$2',
                            principal.actor.subject_id, key)
    if row and (row['request_hash'] != digest or row['organization_id'] is not None or row['auction_id'] != auction_id):
        raise PublicError('idempotency_conflict', 'This key belongs to a different request.', status=409)
    return row


async def receipt(tx, lot, row, principal, key, digest, *, status, code, commitment='pending'):
    prior = decoded(row['outcome']) if row else None
    if prior and prior['status'] != 'pending':
        return prior
    now = await server_now(tx)
    value = {'operation_id': str(row['id'] if row else uuid4()), 'auction_id': str(lot['id']),
        'status': status, 'code': code, 'commitment_status': commitment, 'revision': lot['revision'],
        'accepted_sequence': lot['accepted_sequence'], 'current_minor': lot['current_minor'],
        'next_minimum_minor': next_minimum(lot, decoded(lot['increment_bands'])),
        'server_time': now.isoformat(), 'ends_at': lot['ends_at'].isoformat(), 'end_version': lot['end_version']}
    if row:
        await tx.execute('UPDATE auction_operations SET outcome=$2::jsonb WHERE id=$1', row['id'], json.dumps(value))
    else:
        from uuid import UUID
        await tx.execute('''INSERT INTO auction_operations(id,subject_id,organization_id,operation_key,request_hash,auction_id,outcome)
            VALUES($1,$2,NULL,$3,$4,$5,$6::jsonb)''', UUID(value['operation_id']), principal.actor.subject_id,
            key, digest, lot['id'], json.dumps(value))
    return value


async def expire_known(tx, lot, row, intent, principal, key, digest):
    if not intent or intent['subject_id'] != principal.actor.subject_id or intent['operation_key'] != key:
        return
    if intent['request_hash'] != digest:
        raise PublicError('idempotency_conflict', 'This key belongs to a different bid.', status=409)
    if intent['status'] == 'succeeded':
        code = None
        now = await server_now(tx)
        if now >= lot['ends_at']:
            code = 'auction_ended'
        elif lot['revision'] != intent['bid_revision']:
            code = 'stale_revision'
        elif intent['bid_expires_at'] and now >= intent['bid_expires_at']:
            code = 'fee_preview_required'
        if code:
            await receipt(tx, lot, row, principal, key, digest, status='denied', code=code, commitment='succeeded')


async def prepare(request, dependencies, auction_id, principal, key, digest, *, fee_expires_at=None):
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await operation(tx, principal, key, digest, auction_id)
        lot = await lock_lot(tx, auction_id)
        intent = await tx.fetchrow('SELECT * FROM auction_first_bid_intents WHERE auction_id=$1', auction_id)
        if lot['first_bid_confirmed'] or lot['accepted_sequence']:
            require_bidding(lot)
            await expire_known(tx, lot, prior, intent, principal, key, digest)
            return
        if intent:
            if intent['subject_id'] != principal.actor.subject_id or intent['operation_key'] != key or intent['request_hash'] != digest:
                raise PublicError('sale_mode_pending', 'The first bid commitment is pending reconciliation.', status=409)
            command = decoded(intent['command'])
        else:
            require_bidding(lot)
            if fee_expires_at is None:
                raise PublicError('sale_mode_pending', 'Original first-bid intent is unavailable.', status=503)
            command = None
    if command is None:
        remote = await dependencies.fence_state(request, lot['watch_id'], lot['listing_id'], auction_id)
        if (remote.get('watch_id') != str(lot['watch_id']) or remote.get('listing_id') != str(lot['listing_id'])
                or remote.get('source_id') != str(auction_id) or remote.get('status') != 'fenced'
                or (remote['api_version'] == 2 and remote['listing_revision'] != lot['listing_revision'])):
            raise PublicError('sale_mode_denied', 'The current auction commitment was refused.', status=409)
        if remote.get('auction_committed') is True:
            # Existing V1 fences were already conservative commitments.
            async with unit_of_work(request.app.state.pool) as tx:
                prior = await operation(tx, principal, key, digest, auction_id)
                current = await lock_lot(tx, auction_id)
                require_bidding(current)
                if current['revision'] != lot['revision']:
                    raise PublicError('stale_revision', 'Reload the current auction.', status=409)
                await tx.execute('UPDATE auction_lots SET first_bid_confirmed=true WHERE id=$1', auction_id)
            return
        command = {'operation_key': 'first-bid:' + str(auction_id), 'watch_id': str(lot['watch_id']),
            'listing_id': str(lot['listing_id']), 'listing_revision': remote['listing_revision'],
            'expected_revision': remote['revision'], 'source_id': str(auction_id), 'kind': 'first_bid',
            'reason': 'Commit the first admitted auction bid'}
        async with unit_of_work(request.app.state.pool) as tx:
            prior = await operation(tx, principal, key, digest, auction_id)
            current = await lock_lot(tx, auction_id)
            intent = await tx.fetchrow('SELECT * FROM auction_first_bid_intents WHERE auction_id=$1', auction_id)
            if intent:
                if intent['subject_id'] != principal.actor.subject_id or intent['operation_key'] != key or intent['request_hash'] != digest:
                    raise PublicError('sale_mode_pending', 'First bid commitment is pending.', status=409)
                command = decoded(intent['command'])
            else:
                require_bidding(current)
                if current['revision'] != lot['revision']:
                    raise PublicError('stale_revision', 'Reload the current auction.', status=409)
                await tx.execute('''INSERT INTO auction_first_bid_intents
                    (auction_id,subject_id,operation_key,request_hash,command,bid_revision,bid_expires_at)
                    VALUES($1,$2,$3,$4,$5::jsonb,$6,$7)''', auction_id, principal.actor.subject_id,
                    key, digest, json.dumps(command), current['revision'], fee_expires_at)
                await tx.execute("UPDATE auction_lots SET mode='first_bid_pending' WHERE id=$1", auction_id)
                await receipt(tx, current, prior, principal, key, digest,
                              status='pending', code='first_bid_commitment_pending')
    try:
        result = await dependencies.json('orders', 'GET', '/internal/v2/operations/' + command['operation_key'], request,
            headers=dependencies.service_headers(request, 'orders'), missing=True)
        if result is None:
            result = await dependencies.json('orders', 'POST', '/internal/v2/commitments', request,
                headers={**dependencies.service_headers(request, 'orders'), 'Idempotency-Key': command['operation_key']}, json=command)
    except (PublicError, AccessDenied, HTTPException):
        raise PublicError('sale_mode_pending', 'The first bid commitment is unknown. Retry the same operation.', status=503) from None
    if result.get('status') not in ('succeeded', 'denied'):
        raise PublicError('sale_mode_pending', 'The first bid commitment is not confirmed.', status=503)
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await operation(tx, principal, key, digest, auction_id)
        lot = await lock_lot(tx, auction_id)
        await tx.execute('UPDATE auction_first_bid_intents SET status=$2,outcome=$3::jsonb WHERE auction_id=$1',
                         auction_id, result['status'], json.dumps(result))
        if result['status'] == 'succeeded':
            await tx.execute("UPDATE auction_lots SET mode='bidding',first_bid_confirmed=true WHERE id=$1 AND mode='first_bid_pending'", auction_id)
            await receipt(tx, lot, prior, principal, key, digest, status='pending',
                          code='first_bid_fenced_bid_not_confirmed', commitment='succeeded')
            intent = await tx.fetchrow('SELECT * FROM auction_first_bid_intents WHERE auction_id=$1', auction_id)
            # A known fence can reconcile after expiry, but cannot admit that expired bid.
            prior = await operation(tx, principal, key, digest, auction_id)
            await expire_known(tx, lot, prior, intent, principal, key, digest)
        else:
            await receipt(tx, lot, prior, principal, key, digest, status='denied',
                          code='first_bid_commitment_denied', commitment='denied')
