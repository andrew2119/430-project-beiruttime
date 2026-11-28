"""Finish the original start's release when the seller cannot return."""
import json
from types import SimpleNamespace

from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work

from .auction_start import receipt


async def tick_start_recovery(app):
    pool = app.state.pool
    rows = await pool.fetch('''SELECT id,subject_id,operation_key FROM auction_operations
        WHERE outcome->>'status'='pending'
        AND (outcome->>'code' IN ('auction_start_release_pending','auction_start_expiry_pending')
             OR (outcome->>'code'='auction_start_pending'
                 AND (outcome->>'start_deadline')::timestamptz<=clock_timestamp()))
        AND COALESCE((outcome->>'recovery_after')::timestamptz,'-infinity')<=clock_timestamp()
        ORDER BY created_at,id LIMIT 4''')
    for row in rows:
        try:
            await recover_start(app, row)
        except PublicError:
            # Keep the original durable phase for a bounded retry.
            continue


async def recover_start(app, candidate):
    pool = app.state.pool
    lock = f"operation:{candidate['subject_id']}:{candidate['operation_key']}"
    async with unit_of_work(pool, lock_key=lock) as tx:
        # The same advisory lock as seller start serializes the local decision.
        row = await tx.fetchrow('''UPDATE auction_operations SET outcome=outcome || jsonb_build_object(
              'recovery_after',clock_timestamp()+interval '10 seconds',
              'code',CASE WHEN outcome->>'code'='auction_start_pending' THEN 'auction_start_expiry_pending' ELSE outcome->>'code' END,
              'release_reason',CASE WHEN outcome->>'code'='auction_start_pending' THEN 'schedule_ended' ELSE outcome->>'release_reason' END)
            WHERE id=$1 AND subject_id=$2 AND operation_key=$3 AND outcome->>'status'='pending'
              AND (outcome->>'code' IN ('auction_start_release_pending','auction_start_expiry_pending')
                   OR (outcome->>'code'='auction_start_pending'
                       AND (outcome->>'start_deadline')::timestamptz<=clock_timestamp()))
              AND COALESCE((outcome->>'recovery_after')::timestamptz,'-infinity')<=clock_timestamp()
            RETURNING auction_id,outcome''', candidate['id'], candidate['subject_id'], candidate['operation_key'])
        if row is None:
            return
        value = json.loads(row['outcome'])
        if (value['operation_id'], value['auction_id']) != (str(candidate['id']), str(row['auction_id'])):
            raise ValueError('Unbound pending auction start')
    request = SimpleNamespace(app=app, headers={}, state=SimpleNamespace(request_id='expire-'+str(candidate['id'])))
    dependencies = app.state.auction.dependencies
    if value['code'] == 'auction_start_expiry_pending':
        await dependencies.expire_start_commitment(request, value)
    else:
        await dependencies.release_start_commitment(request, value, 'auction-open:'+value['auction_id'])
    final = receipt(value['auction_id'], value['operation_id'], 'denied', value['release_reason'])
    async with unit_of_work(pool, lock_key=lock) as tx:
        await tx.execute('''UPDATE auction_operations SET outcome=$4::jsonb
            WHERE id=$1 AND outcome->>'status'='pending' AND outcome->>'code'=$2 AND outcome->>'release_reason'=$3''',
            candidate['id'], value['code'], value['release_reason'], json.dumps(final))
