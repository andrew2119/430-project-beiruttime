"""Bounded command boundary; composition supplies authenticated current source reads."""
import asyncio
from datetime import datetime, timezone


class Adapter:
    def __init__(self, store, provider):
        self.store = store
        self.provider = provider

    async def record(self, command, principal):
        try:
            async with asyncio.timeout(1.2):
                current = await self.provider.current(principal, command.job_id, command.organization_id)
        except (TimeoutError, ConnectionError):
            return {'schema_version': 'quality.v1', 'operation_id': str(command.operation_id),
                    'state': 'pending', 'pending_reason': 'source_unavailable',
                    'next_actor': 'business', 'next_review_at': None}
        return self.store.record(command, current, datetime.now(timezone.utc))

    async def operation(self, operation_id, principal, job_id, organization_id):
        async with asyncio.timeout(1.2):
            current = await self.provider.current(principal, job_id, organization_id)
        return self.store.operation(operation_id, current, datetime.now(timezone.utc))
