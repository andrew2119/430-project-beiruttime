"""Bounded expiry transitions preserve history; expiry never authorizes work."""
import asyncio
from uuid import uuid4
from bt_contracts_core.models import EventEnvelope
from bt_contracts.pricing.quotes.events import AssessedQuoteFact
from bt_contracts.pricing.offers.events import OfferFact
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work


async def tick(app):
    async with unit_of_work(app.state.pool) as tx:
        rows = await tx.fetch("""WITH due AS (SELECT id FROM l14_assessed_quotes
            WHERE state='issued' AND expires_at<=clock_timestamp() ORDER BY expires_at,id
            FOR UPDATE SKIP LOCKED LIMIT 30)
            UPDATE l14_assessed_quotes q SET state='expired_return_held' FROM due WHERE q.id=due.id RETURNING q.*""")
        for row in rows:
            await enqueue(tx, EventEnvelope(type=f"pricing.{row['kind']}-quote.expired.v1", source='pricing',
                subject=str(row['id']), request_id=str(uuid4()), data=AssessedQuoteFact(
                    quote_id=row['id'], revision=row['revision'], source_id=row['source_id'],
                    source_revision=row['source_revision'], buyer_id=row['buyer_id'],
                    organization_id=row['organization_id'], state=row['state']).model_dump(mode='json', exclude_none=True)),
                ['pricing-notices-v2', 'accepted-quotes-v1'])
        offers = await tx.fetch("""WITH due AS (SELECT id FROM l14_offers WHERE state='open'
            AND snapshot @> '{"purpose":"offer","currency":"USD","schedule_id":"usd-v2","policy":{"revision":2}}'::jsonb
            AND snapshot #>> '{policy,revision}' = '2'
            AND expires_at<=clock_timestamp() ORDER BY expires_at,id FOR UPDATE SKIP LOCKED LIMIT 30)
            UPDATE l14_offers o SET state='expired',revision=revision+1 FROM due WHERE o.id=due.id RETURNING o.*""")
        for row in offers:
            await enqueue(tx, EventEnvelope(type='pricing.offer.expired.v1', source='pricing', subject=str(row['id']),
                request_id=str(uuid4()), data=OfferFact(offer_id=row['id'], listing_id=row['listing_id'],
                    buyer_id=row['buyer_id'], seller_id=row['seller_id'], seller_organization_id=row['seller_organization_id'],
                    revision=row['revision'], state=row['state']).model_dump(mode='json')), ['pricing-notices-v2'])
    return len(rows) + len(offers)


async def expire(app, stop):
    while not stop.is_set():
        await tick(app)
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
