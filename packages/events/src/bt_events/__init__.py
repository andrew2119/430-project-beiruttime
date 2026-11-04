"""CP B-18: atomic intent, transactional inbox and at-least-once delivery.

Each destination has its own durable row. Relay HTTP runs outside transactions,
uses dedicated dependency clients, bounded dispatch slots and fenced completion.
"""
import asyncio
import json
import math
from typing import Any, Awaitable, Callable
from uuid import uuid4
from bt_contracts_core.models import EventEnvelope as EventEnvelope
from bt_bulkheads import DependencyClient, Unavailable


async def enqueue(tx, event: EventEnvelope, destinations: list[str]) -> None:
    """Destinations are registry keys, never event-supplied URLs."""
    for destination in set(destinations):
        await tx.execute('''INSERT INTO outbox (event_id, destination, envelope)
            VALUES ($1,$2,$3::jsonb) ON CONFLICT (event_id,destination) DO NOTHING''',
            event.id, destination, event.model_dump_json())


async def consume(tx, consumer: str, event: EventEnvelope,
                  handler: Callable[[Any, EventEnvelope], Awaitable[None]]) -> bool:
    """Call in a transaction; handler failure rolls back receipt AND domain work."""
    accepted = await tx.fetchval('''INSERT INTO inbox (consumer,event_id,source)
        VALUES ($1,$2,$3) ON CONFLICT DO NOTHING RETURNING event_id''', consumer, event.id, event.source)
    if accepted is None:
        return False
    await handler(tx, event)
    return True


class OutboxRelay:
    def __init__(self, pool, clients: dict[str, DependencyClient], *,
                 headers: Callable[[str], dict[str, str]], batch_size: int = 20, concurrency: int = 4):
        self.pool, self.clients, self.headers = pool, clients, headers
        self.batch_size = min(max(batch_size, 1), 100)
        self.slots = asyncio.Semaphore(min(max(concurrency, 1), 8))
        longest = max((client.timeout for client in clients.values()), default=1.5)
        self.lease_seconds = max(30, math.ceil(self.batch_size / min(max(concurrency, 1), 8) * (longest + 3)) + 5)

    async def _deliver(self, row, lease) -> int:
        async with self.slots:
            try:
                payload = row['envelope']
                event = EventEnvelope.model_validate(json.loads(payload) if isinstance(payload, str) else payload)
                client = self.clients.get(row['destination'])
                result = (await client.request('POST', '/internal/v1/events', json=event.model_dump(mode='json'),
                    headers={**self.headers(row['destination']), 'X-Request-ID': event.request_id})) if client else Unavailable(row['destination'], 'network')
                ok = not isinstance(result, Unavailable) and 200 <= result.status_code < 300
            except Exception:
                ok = False  # Malformed/configuration failures remain durable, never acknowledged.
            async with self.pool.acquire() as tx:
                if ok:
                    outcome = await tx.execute('''UPDATE outbox SET delivered_at=now(), leased_until=NULL,
                        lease_token=NULL WHERE id=$1 AND lease_token=$2''', row['id'], lease)
                    return int(outcome == 'UPDATE 1')
                await tx.execute('''UPDATE outbox SET available_at=now()+$3*interval '1 second',
                    leased_until=NULL,lease_token=NULL WHERE id=$1 AND lease_token=$2''',
                    row['id'], lease, min(3600, 2 ** min(row['attempts'], 11)))
                return 0

    async def tick(self) -> int:
        destinations = list(self.clients)
        if not destinations:
            return 0
        lease = uuid4()
        async with self.pool.acquire() as tx:
            async with tx.transaction():
                rows = await tx.fetch('''WITH due AS (
                    SELECT id FROM outbox WHERE delivered_at IS NULL
                    AND destination = ANY($4::text[])
                    AND available_at <= now() AND (leased_until IS NULL OR leased_until < now())
                    ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT $1
                ) UPDATE outbox o SET lease_token=$2, leased_until=now()+$3*interval '1 second',
                    attempts=attempts+1 FROM due WHERE o.id=due.id
                    RETURNING o.id,o.destination,o.envelope,o.attempts''', self.batch_size, lease, self.lease_seconds, destinations)
        return sum(await asyncio.gather(*(self._deliver(row, lease) for row in rows)))
