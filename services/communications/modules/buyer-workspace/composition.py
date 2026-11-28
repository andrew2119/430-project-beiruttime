"""Read-only composition: every source remains authoritative for its activity.

No new business state/event is created by a read. Source writes and
notifications use the Auction/Orders owning outboxes, not a second projection
that can falsely turn a pending reservation into a paid order.
"""
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import UUID
from pydantic import ValidationError
from bt_bulkheads import Unavailable
from bt_contracts_core.errors import AccessDenied
from .models import Bids, CurrentBids, CurrentResults, Reservations


class StaleActivityCursor(Exception):
    pass


class ActivityAccessDenied(AccessDenied):
    pass


async def _source(client, path, schema, owner, headers, *, paged=False, activity=False):
    result = await client.request('GET', path, headers=headers)
    if isinstance(result, Unavailable):
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    if result.status_code in (401, 403):
        if activity and result.status_code == 403:
            raise ActivityAccessDenied('Current auction access denied')
        raise AccessDenied('Current buyer access denied')
    if paged and result.status_code == 409:
        raise StaleActivityCursor
    if result.status_code != 200:
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    try:
        records = schema.model_validate(result.json())
    except (ValidationError, ValueError):
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    if any(item.buyer_id != owner for item in records.items):
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    return records


async def compose_reservations(owner: UUID, token: str, request_id: str, orders, *, cursor: UUID | None = None):
    headers = {'Authorization': 'Bearer ' + token, 'X-Request-ID': request_id}
    params = {'limit': 100}
    if cursor is not None:
        params['cursor'] = str(cursor)
    try:
        async with asyncio.timeout(.6):
            reservations = await _source(orders, '/v1/me/reservations?' + urlencode(params),
                                         Reservations, owner, headers)
    except TimeoutError:
        return {'state': 'unavailable', 'items': [], 'next_cursor': None}
    if isinstance(reservations, Reservations):
        ids = [item.reservation_id for item in reservations.items]
        next_cursor = reservations.next_cursor
        if (len(set(ids)) != len(ids) or cursor in ids
                or (next_cursor is not None and (not ids or next_cursor != ids[-1]))):
            return {'state': 'unavailable', 'items': [], 'next_cursor': None}
        active = [item for item in reservations.items if item.currency == 'USD']
        reservations = {
            'state': 'available',
            'next_cursor': str(next_cursor) if next_cursor is not None else None,
            'items': [
                {**item.model_dump(mode='json', exclude={'buyer_id'}),
                 'next_action': {'kind': 'review_reservation', 'href': '/checkout/' + str(item.reservation_id)},
                 'payment_available': False, 'delivery_available': False}
                for item in active
            ],
        }
    return reservations


async def compose(owner: UUID, token: str, request_id: str, auction, orders):
    headers = {'Authorization': 'Bearer ' + token, 'X-Request-ID': request_id}
    bids, reservations = await asyncio.gather(
        _source(auction, '/v1/my-bids?limit=100', Bids, owner, headers),
        compose_reservations(owner, token, request_id, orders),
    )
    if isinstance(bids, Bids):
        bids = {'state': 'available', 'next_cursor': str(bids.next_cursor) if bids.next_cursor else None, 'items': [
            {'auction_id': str(item.auction_id), 'listing_id': str(item.listing_id),
             'status': item.my_status, 'current_price_minor': item.current_price_minor,
             'currency': item.currency, 'revision': item.revision, 'ends_at': item.ends_at.isoformat(),
             'next_action': {'kind': 'view_auction', 'href': '/watches/' + str(item.listing_id)}}
            for item in bids.items if item.status != 'ended']}
    return {'version': 1, 'as_of': datetime.now(timezone.utc).isoformat(),
            'bids': bids, 'reservations': reservations, 'final_results_available': False}


async def compose_current(owner, token, request_id, auction, *, view, cursor=None):
    """Published v2 source contract; an absent producer stays unavailable."""
    if view not in ('leading', 'outbid', 'calendar', 'won', 'lost', 'no_sale', 'unpaid', 'released'):
        raise ValueError('invalid_view')
    is_bid = view in ('leading', 'outbid', 'calendar')
    params = {'limit': 50, 'view': view}
    if cursor:
        if len(cursor) > 200:
            raise ValueError('invalid_cursor')
        params['cursor'] = cursor
    path = ('/v2/my-bids?' if is_bid else '/v2/my-results?') + urlencode(params)
    headers = {'Authorization': 'Bearer ' + token, 'X-Request-ID': request_id}
    unavailable = dict(schema_version=2, state='unavailable', items=[], total=None, next_cursor=None)
    try:
        async with asyncio.timeout(.6):
            records = await _source(auction, path, CurrentBids if is_bid else CurrentResults, owner, headers,
                                    paged=bool(cursor), activity=True)
    except TimeoutError:
        return unavailable
    if isinstance(records, dict):
        return unavailable
    if (len(records.items) > params['limit']
            or len({item.auction_id for item in records.items}) != len(records.items)
            or records.total < len(records.items)
            or (cursor is not None and not records.items)
            or (records.next_cursor is not None
                and (not records.next_cursor or not records.items or records.total == len(records.items)))
            or (cursor is not None and records.next_cursor == cursor)
            or (not cursor and (records.next_cursor is not None) != (records.total > len(records.items)))
            or any((item.status != view if is_bid and view != 'calendar' else
                    item.financial_state not in ('unpaid', 'unpaid_released') if view == 'unpaid' else
                    not item.completed_sale if view == 'released' else
                    item.state != view if not is_bid else False) for item in records.items)):
        return unavailable
    return dict(schema_version=2, state='available', total=records.total,
                next_cursor=records.next_cursor,
                items=[item.model_dump(mode='json', exclude={'buyer_id'}, exclude_unset=True) for item in records.items])
