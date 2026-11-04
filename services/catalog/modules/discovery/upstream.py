"""Only Auction owns bids. Consume its public core v1 HTTP DTOs, never its SQL."""
import asyncio
import os
from decimal import Decimal
from urllib.parse import quote
from pydantic import ValidationError
from bt_bulkheads import DependencyClient, Unavailable
from .auction_contract import History, Snapshot
from .models import AuctionRead, AuctionSnapshot, PublicBid, PublicMoney


async def lifecycle(app, stop):
    client = DependencyClient('auction.public.v1', os.environ.get('AUCTION_API_URL', 'http://auction:8000'), timeout=.6, concurrency=6, failure_threshold=3, cooldown=5)
    orders = DependencyClient('orders.availability.v1', os.environ.get('ORDERS_API_URL','http://orders:8000'), timeout=.35, concurrency=16, failure_threshold=3, cooldown=5)
    identity = DependencyClient('identity.businesses.v1', os.environ.get('IDENTITY_API_URL','http://identity:8000'), timeout=.35, concurrency=8, failure_threshold=3, cooldown=5)
    media = DependencyClient('catalog.public-media.v1', os.environ.get('CATALOG_MEDIA_API_URL','http://127.0.0.1:8000'), timeout=.35, concurrency=8, failure_threshold=3, cooldown=5)
    app.state.discovery_auction = client
    app.state.discovery_orders = orders
    app.state.discovery_identity = identity
    app.state.discovery_media = media
    try:
        await stop.wait()
    finally:
        await asyncio.gather(*(dependency.aclose() for dependency in (client,orders,identity,media)))


def money(minor: int, currency: str):
    return PublicMoney(amount=format(Decimal(minor)/100, '.2f'), currency=currency)


async def read_auction(client, identifier: str, request_id: str | None = None) -> AuctionRead:
    try:
        # Leave time for Catalog and the 1.2s same-origin gateway. No hidden retries.
        async with asyncio.timeout(.85):
            return await _read(client, identifier, request_id)
    except (TimeoutError, ValidationError, ValueError, TypeError, KeyError):
        # No rejected DTO/body or private field enters public errors/logs.
        return AuctionRead(state='unavailable')


async def _response(client, path, headers, params=None):
    response = await client.request('GET', path, headers=headers, params=params)
    return None if isinstance(response, Unavailable) or response.status_code != 200 else response


async def _read(client, identifier: str, request_id: str | None) -> AuctionRead:
    if client is None:
        return AuctionRead(state='unavailable')
    headers = {'X-Request-ID': request_id} if request_id else {}
    response = await _response(client, '/v1/auctions', headers, {'listing_id': identifier})
    if response is None:
        return AuctionRead(state='unavailable')
    body = response.json()
    items = body.get('items') if isinstance(body, dict) else body
    if not isinstance(items, list) or len(items) > 1:
        return AuctionRead(state='unavailable')
    if not items:
        return AuctionRead(state='not_started')
    canonical = Snapshot.model_validate(items[0])
    if canonical.listing_id != identifier:
        return AuctionRead(state='unavailable')
    bids, truncated = [], False
    if canonical.accepted_sequence:
        # CP B-19: history carries its own canonical snapshot. Receipt sequences
        # may have gaps: a private ceiling-only raise adds no public bid. If bids
        # race the first read, resync the bounded window once, never grow a queue.
        for attempt in range(2):
            after = max(0, canonical.accepted_sequence-50)
            response = await _response(client, '/v1/auctions/'+quote(canonical.id, safe='')+'/history', headers, {'after_sequence': after, 'limit': 50})
            if response is None:
                return AuctionRead(state='unavailable')
            history = History.model_validate_json(response.content)
            current = history.snapshot
            if current.id != canonical.id or current.listing_id != identifier or current.revision < canonical.revision or current.accepted_sequence < canonical.accepted_sequence:
                return AuctionRead(state='unavailable')
            sequences = [bid.sequence for bid in history.items]
            if (sequences != sorted(set(sequences))
                or any(sequence <= after or sequence > current.accepted_sequence for sequence in sequences)
                or history.next_sequence != (sequences[-1] if sequences else after)
                or (history.has_more and not sequences)):
                return AuctionRead(state='unavailable')
            canonical = current
            if not history.has_more:
                bids = [PublicBid(sequence=bid.sequence, bidder_label=bid.bidder, amount=money(bid.amount_minor, current.currency), accepted_at=bid.received_at) for bid in history.items]
                truncated = after > 0
                break
            if attempt == 1:
                return AuctionRead(state='unavailable')
    # Ordinary v1 has no independent extension counter. Its authoritative full
    # revision binds ends_at and is the shared end-version token for both viewers.
    snapshot = AuctionSnapshot(auction_id=canonical.id, listing_id=canonical.listing_id,
        revision=canonical.revision, last_sequence=canonical.accepted_sequence,
        current_price=money(canonical.current_minor, canonical.currency),
        opening_price=money(canonical.opening_minor, canonical.currency),
        server_time=canonical.server_time, starts_at=canonical.starts_at, ends_at=canonical.ends_at,
        end_version=canonical.revision,
        status={'live':'open','scheduled':'scheduled','ended':'ended'}[canonical.status],
        bids=bids, history_truncated=truncated)
    return AuctionRead(state='available', snapshot=snapshot)
