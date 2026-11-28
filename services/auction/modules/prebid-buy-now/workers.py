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


async def tick(app, operation_id=None):
    try:
        kernel = get_kernel()
    except PublicError:
        return
    lease = uuid4()
    async with unit_of_work(app.state.pool) as tx:
        row = await tx.fetchrow('''WITH due AS (SELECT id FROM auction_prebid_operations
            WHERE (review_state IN ('outcome_pending','release_pending')
                OR (NOT ended_review_recorded AND scheduled_ends_at<=clock_timestamp()))
            AND ($1::uuid IS NULL OR id=$1) AND available_at<=clock_timestamp()
            AND (lease_until IS NULL OR lease_until<clock_timestamp()) ORDER BY available_at,id
            FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE auction_prebid_operations p SET
            lease_token=$2,lease_until=clock_timestamp()+interval '30 seconds',attempts=attempts+1
            FROM due WHERE p.id=due.id RETURNING p.*''', operation_id, lease)
    if not row:
        return
    remote = None
    allocation = decoded(row['allocation'])
    if row['review_state'] != 'reservation_recorded' and allocation.get('currency') == 'USD':
        try:
            remote = await reconcile_remote(app, allocation, row['remote_key'], 'prebid-'+str(row['id']))
        except Exception:
            pass  # The exact durable intent remains held and retryable.
    async with unit_of_work(app.state.pool) as tx:
        current = await tx.fetchrow('SELECT * FROM auction_prebid_operations WHERE id=$1 FOR UPDATE', row['id'])
        if current['lease_token'] != lease:
            return
        lot = await kernel.lock_lot(tx, row['auction_id'])
        now = await kernel.server_now(tx)
        ended = now >= current['scheduled_ends_at']
        outcome = decoded(current['outcome'])
        review = current['review_state']
        code = current['review_code']
        if remote is not None and remote['status'] == 'succeeded' and review == 'release_pending':
            code = 'legacy_conflicting_outcome'
        elif remote is not None and remote['status'] == 'succeeded':
            if lot['mode'] == 'prebid_pending':
                # Acknowledge only an already committed historical reservation. Never reopen.
                lot = await kernel.transition(tx, lot['id'], expected_revision=lot['revision'],
                    expected_end_version=lot['end_version'], from_mode='prebid_pending', to_mode='prebid_reserved')
            if lot['mode'] == 'prebid_reserved':
                review = 'reservation_recorded'
                code = 'reserved'
                outcome.update(status='succeeded', code='reserved', order_id=remote['order']['id'],
                    reservation_id=remote['order']['id'], quote_id=allocation['quote_id'], revision=lot['revision'])
        elif remote is not None and remote['status'] == 'denied':
            # A refusal is NOT proof of no payment attempt, nor Orders release authority.
            review = 'release_pending'
            if code != 'legacy_conflicting_outcome':
                code = 'legacy_release_pending'
            if outcome['status'] == 'pending':
                outcome.update(status='denied', code='reservation_denied')
        elif review == 'outcome_pending':
            code = 'legacy_outcome_pending' if allocation.get('currency') == 'USD' else 'legacy_currency_review'
        changed = review != current['review_state'] or code != current['review_code'] or ended and not current['ended_review_recorded']
        await tx.execute('''UPDATE auction_prebid_operations SET status=$2,outcome=$3::jsonb,
            review_state=$4,ended_review_recorded=ended_review_recorded OR $5,
            lease_token=NULL,lease_until=NULL,available_at=clock_timestamp()+$6*interval '1 second',review_code=$7 WHERE id=$1''',
            row['id'], outcome['status'], json.dumps(outcome), review, ended,
            300 if review == 'release_pending' else min(300, 2**min(current['attempts'], 8)), code)
        if changed:
            safe = {'auction_id': str(lot['id']), 'listing_id': str(lot['listing_id']),
                'schedule_state': 'ended_legacy_review' if ended else 'within_schedule', 'review_state': review,
                'financial_state': 'held', 'scheduled_ends_at': current['scheduled_ends_at'].isoformat(),
                'revision': lot['revision'], 'end_version': lot['end_version']}
            await enqueue(tx, EventEnvelope(type='auction.legacy-purchase-review.v2', source='auction', subject=str(lot['id']),
                request_id='prebid-'+str(row['id']), data=safe), ['communications-auction-policy-v2'])


async def run(app, stop):
    while not stop.is_set():
        await tick(app)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass
