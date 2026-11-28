"""Bounded adapter for the authoritative Orders journal refund transaction."""
import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol, Callable
from uuid import UUID
from bt_contracts.orders.refunds.v1 import Authority, Command, Facts, Operation, Plan
from .domain import Refused, plan, scope


class Transaction(Protocol):
    async def authority(self, command: Command) -> Authority: ...
    async def prior(self, command: Command) -> Operation | None: ...
    async def facts(self, command: Command) -> Facts: ...
    async def reserve(self, plan: Plan) -> Operation: ...


class Journal(Protocol):
    def refund_transaction(self, command: Command) -> AbstractAsyncContextManager[Transaction]: ...
    async def lookup(self, operation_id: UUID, actor_id: UUID, organization_id: UUID) -> Operation | None: ...


class Refunds:
    def __init__(self, journal: Journal, clock: Callable[[], datetime]):
        self.journal = journal
        self.clock = clock

    async def request(self, command: Command) -> Operation:
        try:
            async with asyncio.timeout(2):
                async with self.journal.refund_transaction(command) as tx:
                    # Even identical retries must pass current permission before a private read.
                    scope(command, await tx.authority(command))
                    prior = await tx.prior(command)
                    if prior is not None:
                        return prior
                    facts = await tx.facts(command)
                    return await tx.reserve(plan(command, facts, await tx.authority(command), self.clock()))
        except (TimeoutError, ConnectionError):
            # The caller must look up/retry this exact immutable command. No new action is created.
            raise Refused('pending') from None

    async def lookup(self, operation_id: UUID, actor_id: UUID, organization_id: UUID):
        try:
            async with asyncio.timeout(2):
                return await self.journal.lookup(operation_id, actor_id, organization_id)
        except (TimeoutError, ConnectionError):
            raise Refused('unavailable') from None
