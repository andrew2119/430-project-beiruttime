"""An ordered private outbox for each auction's committed allocation history."""
import json
from datetime import timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response
from bt_contracts_core.errors import PublicError
from service_app.service_auth import service

router = APIRouter(prefix='/internal/v2/auctions')


async def retain_support(tx, row, *, listing_id, watch_id, financial_revision=None):
    order = row['order_id']
    reason = row['state'] if row['state'] in ('allocation_pending', 'allocation_denied') else None
    if row['winner_id'] is None or (reason is None and (row['state'] != 'closed' or order is None
            or type(financial_revision) is not int or financial_revision < 1)):
        raise ValueError('Unbound support transition')
    if reason is not None and (order is not None or financial_revision is not None):
        raise ValueError('Unbound support transition')
    facts = dict(schema_version=1, auction_id=str(row['auction_id']), listing_id=str(listing_id), watch_id=str(watch_id),
                 buyer_id=str(row['winner_id']), order_id=str(order) if order is not None else None,
                 result_revision=row['result_revision'], financial_revision=financial_revision,
                 held_since=row['created_at'].astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'), reason=reason)
    await tx.execute('INSERT INTO l13_auction_support_outbox(event_id,auction_id,result_revision,facts) VALUES($1,$2,$3,$4::jsonb)',
                     uuid4(), row['auction_id'], row['result_revision'], json.dumps(facts))


async def deliver_support(pool, sources):
    token = uuid4()
    rows = await pool.fetch('''WITH first AS MATERIALIZED (
        SELECT o.event_id FROM l13_auction_support_outbox o
        WHERE o.delivered_at IS NULL AND o.available_at<=clock_timestamp()
        AND (o.lease_until IS NULL OR o.lease_until<=clock_timestamp())
        AND NOT EXISTS (SELECT 1 FROM l13_auction_support_outbox older WHERE older.auction_id=o.auction_id
          AND older.result_revision<o.result_revision AND older.delivered_at IS NULL)
        ORDER BY o.available_at,o.auction_id,o.result_revision LIMIT 3 FOR UPDATE OF o SKIP LOCKED
    ) UPDATE l13_auction_support_outbox o SET lease_token=$1,lease_until=clock_timestamp()+interval '15 seconds'
    FROM first WHERE o.event_id=first.event_id RETURNING o.event_id,o.facts''', token)
    for row in rows:
        try:
            facts = json.loads(row['facts'])
            reply = await sources.json('communications', 'POST', '/internal/v1/support/auction-results/events',
                                       json={'event_id': str(row['event_id']), 'facts': facts})
        except (PublicError, ValueError, TypeError):
            reply = None
        if reply == {'accepted': True} and reply['accepted'] is True:
            await pool.execute('''UPDATE l13_auction_support_outbox SET delivered_at=clock_timestamp(),lease_token=NULL,lease_until=NULL
                WHERE event_id=$1 AND lease_token=$2 AND delivered_at IS NULL''', row['event_id'], token)
        else:
            await pool.execute('''UPDATE l13_auction_support_outbox SET available_at=clock_timestamp()+interval '5 seconds',
                lease_token=NULL,lease_until=NULL WHERE event_id=$1 AND lease_token=$2 AND delivered_at IS NULL''', row['event_id'], token)


@router.get('/{auction_id}/support-delivery-binding')
async def delivery_binding(auction_id: UUID, order_id: UUID, request: Request, response: Response):
    service(request, {'orders'})
    row = await request.app.state.pool.fetchrow('''SELECT o.facts FROM l13_auction_support_outbox o
        JOIN l13_auction_closes c ON c.auction_id=o.auction_id AND c.result_revision=o.result_revision
        WHERE o.auction_id=$1 AND c.order_id=$2 AND c.state='closed' AND o.delivered_at IS NOT NULL
          AND o.facts->>'order_id'=$3 AND o.facts->>'reason' IS NULL''', auction_id, order_id, str(order_id))
    if row is None:
        raise PublicError('auction_support_binding_unavailable', 'The allocation support decision is not confirmed.', status=503)
    response.headers['Cache-Control'] = 'no-store'
    facts = json.loads(row['facts'])
    return {key: facts[key] for key in ('auction_id', 'listing_id', 'watch_id', 'buyer_id', 'order_id', 'result_revision', 'held_since')}
