import asyncio
import json
from uuid import uuid4
from bt_contracts_core.models import EventEnvelope
from bt_contracts_core.errors import PublicError
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.engine import decoded
from .kernel import get_kernel
from .dependencies import reconcile_remote


async def tick(app,operation_id=None):
    try:kernel=get_kernel()
    except PublicError:return  # Leave durable pending intent untouched until the provider is available.
    lease=uuid4()
    async with unit_of_work(app.state.pool) as tx:
        row=await tx.fetchrow('''WITH due AS (SELECT id FROM auction_prebid_operations WHERE status='pending'
            AND ($1::uuid IS NULL OR id=$1) AND available_at<=clock_timestamp()
            AND (lease_until IS NULL OR lease_until<clock_timestamp()) ORDER BY available_at,id
            FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE auction_prebid_operations p SET
            lease_token=$2,lease_until=clock_timestamp()+interval '30 seconds',attempts=attempts+1
            FROM due WHERE p.id=due.id RETURNING p.*''',operation_id,lease)
    if not row: return
    try:
        remote=await reconcile_remote(app,decoded(row['allocation']),row['remote_key'],'prebid-'+str(row['id']))
    except Exception:
        remote=None
    async with unit_of_work(app.state.pool) as tx:
        # Claim completion is fenced; an expired worker cannot overwrite a newer attempt.
        current=await tx.fetchrow('SELECT * FROM auction_prebid_operations WHERE id=$1 FOR UPDATE',row['id'])
        if current['lease_token']!=lease or current['status']!='pending': return
        if remote is None:
            await tx.execute('''UPDATE auction_prebid_operations SET lease_token=NULL,lease_until=NULL,
                available_at=clock_timestamp()+$2*interval '1 second' WHERE id=$1''',row['id'],min(300,2**min(current['attempts'],8)))
            return
        lot=await kernel.lock_lot(tx,row['auction_id'])
        if lot['mode']!='prebid_pending': return
        outcome=decoded(current['outcome'])
        if remote['status']=='succeeded':
            updated=await kernel.transition(tx,lot['id'],expected_revision=lot['revision'],expected_end_version=lot['end_version'],
                from_mode='prebid_pending',to_mode='prebid_reserved')
            outcome.update(status='succeeded',code='reserved',order_id=remote['order']['id'],
                reservation_id=remote['order']['id'],quote_id=decoded(row['allocation'])['quote_id'],revision=updated['revision'])
        else:
            # Known denial is held too: no speculative relist or remote fence release in this module.
            outcome.update(status='denied',code='reservation_denied')
        await tx.execute('''UPDATE auction_prebid_operations SET status=$2,outcome=$3::jsonb,
            lease_token=NULL,lease_until=NULL WHERE id=$1''',row['id'],outcome['status'],json.dumps(outcome))
        safe={'auction_id':str(lot['id']),'listing_id':str(lot['listing_id']),'status':outcome['status'],
            'mode':'prebid_reserved' if outcome['status']=='succeeded' else 'prebid_pending','revision':outcome['revision'],'end_version':lot['end_version']}
        # Destination not enabled until Communications publishes a receiver for this schema.
        await enqueue(tx,EventEnvelope(type='auction.prebid-resolved.v1',source='auction',subject=str(lot['id']),
            request_id='prebid-'+str(row['id']),data=safe),['communications-auction-policy-v1'])


async def run(app,stop):
    while not stop.is_set():
        await tick(app)
        try: await asyncio.wait_for(stop.wait(),timeout=2)
        except asyncio.TimeoutError: pass
