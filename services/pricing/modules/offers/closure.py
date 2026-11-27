"""Bounded cross-route reconciliation from authoritative facts, not UI guesses."""
from bt_runtime.app.db import unit_of_work
from service_app import peers
from .routes import CURRENT_TERMS, notice


def committed(watch, row):
    return (watch.get('watch_id') == str(row['watch_id'])
            and watch.get('listing_id') == str(row['listing_id'])
            and type(watch.get('listing_revision')) is int
            and watch['listing_revision'] >= row['listing_revision']
            and watch.get('status') in ('reserved', 'withdrawn'))


async def close_other_route(request, row):
    watch = await peers.call(request, 'orders', 'GET', f"/internal/v2/watches/{row['watch_id']}", internal=True)
    close = committed(watch, row)
    if not close:
        listing = await peers.call(request, 'catalog', 'GET', f"/v1/listings/{row['listing_id']}/publication", missing=True)
        close = bool(listing and listing.get('id') == str(row['listing_id']) and listing.get('status') == 'withdrawn'
                     and type(listing.get('revision')) is int and listing['revision'] >= row['listing_revision'])
    if not close:
        return 0  # Missing/hidden/pending/unknown is not an invented withdrawal.
    async with unit_of_work(request.app.state.pool, lock_key='offer-listing:' + str(row['listing_id'])) as tx:
        closed = await tx.fetch(f"""UPDATE l14_offers SET state='closed',revision=revision+1
            WHERE watch_id=$1 AND listing_id=$2 AND state='open' AND {CURRENT_TERMS} RETURNING *""", row['watch_id'], row['listing_id'])
        for offer in closed:
            await notice(tx, request, offer, 'closed')
    return len(closed)
