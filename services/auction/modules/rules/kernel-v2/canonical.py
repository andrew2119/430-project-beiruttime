"""Borrow the caller's transaction for canonical v4 mode changes and receipts."""
import json
from datetime import timedelta

from bt_contracts.auction.core.kernel_v4 import KernelReceipt, decide


async def execute(tx, command, authorize):
    """authorize rechecks current authority, cancellation release and legacy refusal.

    The caller owns commit/rollback. No remote calls are permitted in authorize.
    Acquire operation before auction, matching admission's advisory lock namespace.
    """
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                     f'operation:{command.actor_id}:{command.operation_id}')
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                     'auction:' + str(command.auction_id))
    lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1 FOR UPDATE', command.auction_id)
    # Current authority is required even when returning a retained private receipt.
    responsible = await authorize(tx, command, lot)
    retained = await tx.fetchrow('SELECT command,receipt FROM l14_kernel_operations WHERE operation_id=$1',
                                 command.operation_id)
    payload = command.model_dump(mode='json')
    if retained:
        old = json.loads(retained['command']) if isinstance(retained['command'], str) else retained['command']
        if old != payload:
            raise ValueError('Operation reference conflicts with the retained request')
        return KernelReceipt.model_validate_json(retained['receipt']) if isinstance(
            retained['receipt'], str) else KernelReceipt.model_validate(retained['receipt'])
    if lot is None or lot['watch_id'] != command.watch_id:
        raise ValueError('Auction and watch reference must match')
    now = await tx.fetchval('SELECT clock_timestamp()')
    if lot['revision'] != command.expected_revision:
        mode, state, code = lot['mode'], 'denied', 'stale_revision'
    else:
        mode, state, code = decide(lot, command.action, now)
    if mode != lot['mode']:
        lot = await tx.fetchrow('''UPDATE auction_lots SET mode=$2,revision=revision+1,
            close_version=close_version+CASE WHEN $2 IN
            ('closed_no_sale','closed_winner','ended_legacy_review') AND mode<>'ended_legacy_review'
            THEN 1 ELSE 0 END
            WHERE id=$1 RETURNING *''', command.auction_id, mode)
    pending_reason = code if state == 'pending' or code == 'allocation_pending' else None
    receipt = KernelReceipt(pending_reason=pending_reason,
        next_actor=responsible if pending_reason else None,
        next_review_at=now + timedelta(hours=24) if pending_reason else None, **{key: payload[key] for key in (
        'operation_id', 'auction_id', 'watch_id', 'actor_id', 'organization_id',
        'expected_revision', 'policy_revision')}, state=state, code=code,
        mode=mode, revision=lot['revision'], server_time=now)
    await tx.execute('''INSERT INTO l14_kernel_operations(operation_id,auction_id,command,receipt)
        VALUES($1,$2,$3::jsonb,$4::jsonb)''', command.operation_id, command.auction_id,
        json.dumps(payload), receipt.model_dump_json())
    # The receipt is the durable local event intent. Its consumer uses operation_id
    # as the stable delivery key and must never allocate from a public projection.
    return receipt


async def lookup(tx, command, authorize):
    """Read a retained result without creating or advancing an operation."""
    lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', command.auction_id)
    await authorize(tx, command, lot)
    retained = await tx.fetchrow('SELECT command,receipt FROM l14_kernel_operations WHERE operation_id=$1',
                                 command.operation_id)
    if retained is None:
        raise ValueError('Operation result is unavailable')
    old = json.loads(retained['command']) if isinstance(retained['command'], str) else retained['command']
    if old != command.model_dump(mode='json'):
        raise ValueError('Operation reference conflicts with the retained request')
    return KernelReceipt.model_validate_json(retained['receipt']) if isinstance(
        retained['receipt'], str) else KernelReceipt.model_validate(retained['receipt'])
