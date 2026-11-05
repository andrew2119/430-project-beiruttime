"""Auction kernel v2: service-local callers borrow a transaction, never commit it.

Lock order: operation -> listing (creation only) -> auction. All modes, bid
admission, policy extensions and close decisions use this exact auction lock.
"""
import json
from datetime import datetime
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
    allowed = {('bidding', 'prebid_pending'), ('prebid_pending', 'prebid_reserved'),
               ('bidding', 'closed_no_sale'), ('bidding', 'closed_winner')}
    if (from_mode, to_mode) not in allowed:
        raise ValueError('Invalid auction mode transition')
    lot = await lock_lot(tx, auction_id)
    if (lot['revision'] != expected_revision or lot['end_version'] != expected_end_version
            or lot['mode'] != from_mode):
        raise PublicError('stale_revision', 'Reload the current auction.', status=409)
    if to_mode == 'prebid_pending' and (lot['accepted_sequence'] != 0 or lot['first_bid_confirmed']):
        raise PublicError('first_bid_exists', 'Buy Now is unavailable after the first bid.', status=409)
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
    """Pure L12 accepted-bid hook: ISO UTC state -> extended, ends_at, end_version.

    One invocation per admitted command, including proxy responses. A private
    maximum raise with no public bid does not extend the deadline.
    """
    if lot['extension_policy'] == 'none.v1' or not result['bids']:
        return lot['ends_at'], lot['end_version']
    hook = hooks.get('auction.policy.accepted-bid.v1')
    if hook is None:
        raise PublicError('policy_unavailable', 'Auction timing policy is unavailable.', status=503)
    try:
        value = hook({'ends_at': lot['ends_at'].isoformat(), 'end_version': lot['end_version'],
                      'extension_policy': lot['extension_policy'], 'server_time': now.isoformat()})
        end = datetime.fromisoformat(value['ends_at'])
        version = value['end_version']
        changed = end != lot['ends_at']
        if (end.tzinfo is None or type(version) is not int or type(value['extended']) is not bool
                or value['extended'] != changed or end < lot['ends_at']
                or version != lot['end_version'] + int(changed)
                or (end - lot['ends_at']).total_seconds() > 120):
            raise ValueError()
        return end, version
    except Exception:
        raise PublicError('policy_unavailable', 'Auction timing policy is unavailable.', status=503) from None
