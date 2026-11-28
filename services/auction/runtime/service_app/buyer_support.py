"""Current held-result authority for the transaction's support conversation."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from bt_contracts_core.errors import AccessDenied, PublicError

from .buyer_activity import CLOSE_FIELDS, financial_facts, unavailable
from .private_maximum import own_bidder, require_access
from .service_auth import service

router = APIRouter(prefix='/internal/v2/auctions', tags=['buyer-support'])


def buyer_request(request):
    value = request.headers.get('x-buyer-authorization', '')
    scheme, _, token = value.partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    headers = [(k, v) for k, v in request.scope['headers'] if k not in (b'authorization', b'x-buyer-authorization')]
    return Request({**request.scope, 'headers': [*headers, (b'authorization', value.encode('latin-1'))]})


async def result(request, auction_id):
    async with request.app.state.pool.acquire() as db:
        return await db.fetchrow(f'''SELECT {CLOSE_FIELDS}, c.created_at AS held_since,
            EXISTS(SELECT 1 FROM l13_auction_support_outbox o WHERE o.auction_id=c.auction_id
                AND o.result_revision=c.result_revision) AS support_transition_retained
            FROM l13_auction_closes c JOIN auction_lots a ON a.id=c.auction_id WHERE a.id=$1''', auction_id)


@router.get('/{auction_id}/buyer-support')
async def buyer_support(auction_id: UUID, request: Request, response: Response, include_resolved: bool = False):
    service(request, {'communications'})
    engine = request.app.state.auction
    principal = await own_bidder(engine, buyer_request(request))
    row = await result(request, auction_id)
    require_access(row, principal)
    if row['winner_id'] != principal.actor.subject_id:
        raise AccessDenied('Current winner support access required')
    if row['state'] in ('allocation_denied', 'closed') and not row['support_transition_retained']:
        if include_resolved:
            raise PublicError('support_history_missing', 'No support history is available for this result.', status=404)
        raise AccessDenied('The result has no current support admission')
    held_since = row['held_since']
    if not isinstance(held_since, datetime) or held_since.utcoffset() is None:
        raise unavailable()
    order = row['order_id']
    financial_revision = None
    if row['state'] in ('allocation_pending', 'allocation_denied') and order is None:
        reason = row['state']
    elif row['state'] == 'closed' and order is not None:
        fact = (await financial_facts(request, engine, [row]))[order]
        if row != await result(request, auction_id):
            raise unavailable()
        if fact.state != 'unknown' and not include_resolved:
            raise AccessDenied('The auction does not have an uncertain payment')
        financial_revision = fact.revision
        reason = 'payment_unknown' if fact.state == 'unknown' else None
    else:
        raise AccessDenied('The auction does not have a current held result')
    response.headers['Cache-Control'] = 'no-store'
    return dict(schema_version=1, auction_id=str(auction_id), listing_id=str(row['listing_id']),
                watch_id=str(row['watch_id']), buyer_id=str(principal.actor.subject_id),
                order_id=str(order) if order is not None else None, result_revision=row['result_revision'],
                financial_revision=financial_revision, reason=reason,
                held_since=held_since.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'))
