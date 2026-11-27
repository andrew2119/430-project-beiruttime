"""Durable adapter around an injected canonical source, never a second authority."""
from contextlib import asynccontextmanager
from bt_contracts_core.models import EventEnvelope
from bt_contracts.orders.cancellations.v1 import Facts, Result
from bt_events import enqueue
from . import repository
from .service import Denied


class TransactionalProvider:
    def __init__(self, pool, source):
        self.pool = pool
        self.source = source

    @asynccontextmanager
    async def transaction(self, command, principal):
        async with self.pool.acquire() as tx:
            async with tx.transaction():
                await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                                 'l13-cancellation:' + str(command.operation_id))
                facts = await self.source.lock(tx, command.subject_id, command.watch_id, principal)
                yield Transaction(tx, self.source, Facts.model_validate(facts), principal)

    async def lookup(self, subject_id, operation_id, principal):
        async with self.pool.acquire() as tx:
            async with tx.transaction():
                facts = Facts.model_validate(await self.source.lock(tx, subject_id, None, principal))
                if not await self.source.authorized(tx, facts, principal, 'read'):
                    raise Denied()
                value = await repository.receipt(tx, operation_id)
                if value is None:
                    return None
                result = value['result']
                if (value['actor_id'] != str(principal.actor.subject_id)
                        or result.subject_id != subject_id
                        or result.organization_id != principal.actor.organization_id):
                    raise Denied()
                current = Result.model_validate(await self.source.current(tx, facts, result, principal))
                bindings = ('operation_id', 'subject_id', 'watch_id', 'actor_id',
                            'organization_id', 'expected_revision')
                if (any(getattr(current, key) != getattr(result, key) for key in bindings)
                        or current.revision != facts.revision):
                    raise Denied()
                return current


class Transaction:
    def __init__(self, tx, source, facts, principal):
        self.tx, self.source, self.principal = tx, source, principal
        self.current = facts
        self.facts = facts.model_dump()

    async def authorized(self, action):
        if action == 'request' and self.current.buyer_id != self.principal.actor.subject_id:
            return False
        if action in ('accept', 'decline') and self.current.buyer_id == self.principal.actor.subject_id:
            return False
        return await self.source.authorized(self.tx, self.current, self.principal, action)

    async def receipt(self, operation_id):
        return await repository.receipt(self.tx, operation_id)

    async def apply(self, result):
        if result.state != 'denied':
            await self.source.apply(self.tx, self.current, result)

    async def save(self, command, principal, result):
        await repository.save(self.tx, command, principal, self.current, result)
        await enqueue(self.tx, EventEnvelope(
            type='orders.cancellation-changed.v1', source='orders',
            subject=str(result.subject_id), request_id=command.operation_id.hex,
            data={'operation_id': str(result.operation_id), 'subject_id': str(result.subject_id),
                  'revision': result.revision}), ['communications'])
