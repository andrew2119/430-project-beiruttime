"""Auction kernel v2: service-local callers borrow a transaction, never commit it.

Lock order: operation -> listing (creation only) -> auction. All modes, bid
admission and close decisions use this exact auction lock.
"""
import json
from bt_contracts_core.errors import PublicError

MODES = frozenset({'bidding', 'first_bid_pending', 'listing_edit_pending', 'prebid_pending', 'prebid_reserved', 'closed_no_sale', 'closed_winner'})


async def lock_lot(tx, auction_id):
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'auction:' + str(auction_id))
    lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1 FOR UPDATE', auction_id)
    if lot is None:
        raise PublicError('not_found', 'Auction not found.', status=404)
    return lot


async def server_now(tx):
    return await tx.fetchval('SELECT clock_timestamp()')


def require_bidding(lot):
    if lot['mode'] != 'bidding':
        raise PublicError('sale_mode_pending' if lot['mode'] in ('prebid_pending', 'first_bid_pending', 'listing_edit_pending') else 'auction_committed',
                          'Bidding is held by the current sale commitment.', status=409)


async def transition(tx, auction_id, *, expected_revision, expected_end_version, from_mode, to_mode):
    """Call only in the caller's unit of work. Returns the locked current row.

    Pending is durable BEFORE remote reservation. Known denial and unknown
    remote outcomes retain their held mode for stable reconciliation.
    """
    if from_mode not in MODES or to_mode not in MODES:
        raise ValueError('Unknown auction mode')
    if to_mode == 'prebid_pending':
        raise PublicError('auction_purchase_disabled', 'Buy Now is available only for fixed-price listings.', status=409)
    allowed = {('prebid_pending', 'prebid_reserved'),
               ('bidding', 'closed_no_sale'), ('bidding', 'closed_winner')}
    if (from_mode, to_mode) not in allowed:
        raise ValueError('Invalid auction mode transition')
    lot = await lock_lot(tx, auction_id)
    if (lot['revision'] != expected_revision or lot['end_version'] != expected_end_version
            or lot['mode'] != from_mode):
        raise PublicError('stale_revision', 'Reload the current auction.', status=409)
    if to_mode.startswith('closed_') and await server_now(tx) < lot['ends_at']:
        raise PublicError('auction_not_ended', 'The current auction end has not passed.', status=409)
    updated = await tx.fetchrow('''UPDATE auction_lots SET mode=$2,revision=revision+1,
        close_version=close_version + CASE WHEN $2 LIKE 'closed_%' THEN 1 ELSE 0 END
        WHERE id=$1 RETURNING *''', auction_id, to_mode)
    if to_mode.startswith('closed_'):
        # No bid can finish outside this same lock. A retained pending fence is
        # not an accepted bid and must not remain an imaginary winning operation.
        await tx.execute("""UPDATE auction_operations SET outcome=outcome || $2::jsonb
            WHERE auction_id=$1 AND outcome->>'status'='pending'""", auction_id, json.dumps({
                'status': 'denied', 'code': 'auction_ended', 'revision': updated['revision'],
                'end_version': updated['end_version'], 'current_minor': updated['current_minor'],
                'accepted_sequence': updated['accepted_sequence'], 'ends_at': updated['ends_at'].isoformat(),
                'server_time': (await server_now(tx)).isoformat()}))
    return updated


def extension(hooks, lot, result, now):
    """Compatibility seam: no policy hook is invoked; the scheduled end wins."""
    return lot['scheduled_ends_at'], lot['end_version']
