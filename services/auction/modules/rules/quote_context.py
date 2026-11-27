"""Minimal service-only exact-price source, never expose reserve/private maxima."""
from typing import Literal
from uuid import UUID
import jwt
from fastapi import APIRouter, Request, HTTPException
from bt_contracts_core.errors import AccessDenied, PublicError

router = APIRouter()


@router.get('/internal/v2/auctions/{auction_id}/quote-context')
async def context(auction_id: UUID, buyer_id: UUID, kind: Literal['prebid', 'winner'], request: Request):
    settings = request.app.state.settings
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or not settings.service_auth_public_key:
        raise HTTPException(401)
    try:
        claims = jwt.decode(token, settings.service_auth_public_key, algorithms=['RS256'], audience='auction',
            issuer=settings.auth_issuer, options={'require': ['sub', 'type', 'iss', 'aud', 'iat', 'exp']})
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    if claims['sub'] != 'pricing' or claims['type'] != 'service':
        raise AccessDenied('Wrong quote source consumer')
    async with request.app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
        now = await tx.fetchval('SELECT clock_timestamp()')
    if not lot:
        raise PublicError('not_found', 'Auction not found.', status=404)
    if buyer_id == lot['seller_id']:
        raise AccessDenied('Self purchase is not permitted')
    if kind == 'winner':
        if lot['mode'] != 'closed_winner' or lot['leader_id'] != buyer_id or now < lot['ends_at']:
            raise PublicError('quote_source_invalid', 'A current closed winner is required.', status=409)
        price = lot['current_minor']
    else:
        price = lot.get('buy_now_minor')
        if (lot['mode'] != 'bidding' or lot['accepted_sequence'] or lot['first_bid_confirmed'] or price is None
                or now < lot['starts_at'] or now >= lot['ends_at']):
            raise PublicError('quote_source_invalid', 'Buy Now must precede the first bid and current deadline.', status=409)
    return {'auction_id': str(auction_id), 'listing_id': str(lot['listing_id']), 'watch_id': str(lot['watch_id']),
        'buyer_id': str(buyer_id), 'seller_id': str(lot['seller_id']),
        'seller_organization_id': str(lot['seller_organization_id']) if lot['seller_organization_id'] else None,
        'revision': lot['revision'], 'listing_revision': lot['listing_revision'], 'end_version': lot['end_version'],
        'close_version': lot['close_version'], 'mode': lot['mode'],
        'currency': lot['currency'], 'price_minor': price, 'ends_at': lot['ends_at'].isoformat()}
