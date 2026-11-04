"""Read-only composition: every source remains authoritative for its activity.

CP B-18: no new business state/event is created by a read. Source writes and
notifications use the Auction/Orders owning outboxes, not a second projection
that can falsely turn a pending reservation into a paid order.
"""
import asyncio
from datetime import datetime, timezone
from uuid import UUID
from pydantic import ValidationError
from bt_bulkheads import Unavailable
from bt_contracts_core.errors import AccessDenied
from .models import Bids, Reservations


async def _source(client, path, schema, owner, headers):
    result = await client.request('GET', path, headers=headers)
    if isinstance(result, Unavailable):
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    if result.status_code in (401, 403):
        # Do not render another source's private data alongside a revoked session.
        raise AccessDenied('Current buyer access denied')
    if result.status_code != 200:
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    try:
        records = schema.model_validate(result.json())
    except (ValidationError, ValueError):
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    if any(item.buyer_id != owner for item in records.items):
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    return records


async def compose(owner: UUID, token: str, request_id: str, auction, orders):
    headers = {'Authorization': 'Bearer ' + token, 'X-Request-ID': request_id}
    bids, reservations = await asyncio.gather(
        _source(auction, '/v1/my-bids?limit=100', Bids, owner, headers),
        _source(orders, '/v1/me/reservations?limit=100', Reservations, owner, headers),
    )
    if isinstance(bids, Bids):
        bids = {'state': 'available', 'next_cursor': str(bids.next_cursor) if bids.next_cursor else None, 'items': [
            {'auction_id': str(item.auction_id), 'listing_id': str(item.listing_id),
             'status': item.my_status, 'current_price_minor': item.current_price_minor,
             'currency': item.currency, 'revision': item.revision, 'ends_at': item.ends_at.isoformat(),
             'next_action': {'kind': 'view_auction', 'href': '/watches/' + str(item.listing_id)}}
            for item in bids.items if item.status != 'ended']}
    if isinstance(reservations, Reservations):
        reservations = {'state': 'available', 'next_cursor': str(reservations.next_cursor) if reservations.next_cursor else None, 'items': [
            {**item.model_dump(mode='json', exclude={'buyer_id'}),
             'next_action': {'kind': 'review_reservation', 'href': '/checkout?order=' + str(item.reservation_id)},
             'payment_available': False, 'delivery_available': False}
            for item in reservations.items]}
    return {'version': 1, 'as_of': datetime.now(timezone.utc).isoformat(),
            'bids': bids, 'reservations': reservations, 'final_results_available': False}
