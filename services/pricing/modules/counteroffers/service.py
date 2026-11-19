"""Bounded entry boundary; provider retains serialization and durable recovery."""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Protocol
from bt_contracts.pricing.counteroffers.current import Command, Result
from .engine import decide

class Provider(Protocol):
    async def execute(self, command: Command, decision) -> Result:
        """Recheck scope, recover receipt or decide and commit under canonical lock.

        Reconcile allocation_required through Q02 before returning succeeded.
        Persist intent before dependency calls; pending operations fence this watch.
        """
        ...

    async def current(self, principal, subject_id):
        """Recheck scope and canonical availability; close expired offers atomically."""
        ...

    async def lookup(self, principal, subject_id, operation_id) -> Result:
        """Private scoped lookup, including current revocation checks."""
        ...

class Counteroffers:
    def __init__(self, provider: Provider):
        self.provider = provider

    async def command(self, command: Command):
        try:
            async with asyncio.timeout(2):
                return await self.provider.execute(command, decide)
        except (TimeoutError, ConnectionError):
            return Result(**command.model_dump(include={'operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision'}), state='pending',
                          code='retry_same_operation', revision=command.expected_revision,
                          next_actor='support', pending_reason='outcome_unknown',
                          next_review_at=datetime.now(timezone.utc) + timedelta(hours=24))

    async def operation(self, principal, subject_id, operation_id):
        async with asyncio.timeout(2):
            return await self.provider.lookup(principal, subject_id, operation_id)

    async def current(self, principal, subject_id):
        async with asyncio.timeout(2):
            return await self.provider.current(principal, subject_id)
