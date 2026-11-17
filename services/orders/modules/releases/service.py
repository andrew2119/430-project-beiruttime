"""Bounded facade over the sole Orders release/journal API."""
import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from .contracts import Command, Context, Operation, Snapshot
from .policy import conditions, preview

Decision = Callable[[Snapshot, datetime, Command], tuple[str, ...]]


class Denied(Exception):
    """Current authority is absent, or the stable operation has conflicting content."""


class ReleaseJournal(Protocol):
    """All methods enforce current scope. Reserve is one canonical transaction.

    Reserve invokes decide on current locked facts and persists denied or pending
    outcomes, reservations and outbox together. Lookup/reconcile bind their caller
    to the original operation. Reconcile never creates a new transfer.
    """

    async def current(self, context: Context, order_id: UUID) -> Snapshot: ...
    async def reserve(self, command: Command, decide: Decision) -> Operation: ...
    async def lookup(self, context: Context, operation_id: UUID) -> Operation: ...
    async def reconcile(self, context: Context, operation_id: UUID) -> Operation: ...


class Releases:
    def __init__(self, journal: ReleaseJournal, *, clock=None, timeout=4.0):
        if not 0 < timeout <= 4:
            raise ValueError("invalid_deadline")
        self.journal = journal
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timeout = timeout

    async def _call(self, call):
        async with asyncio.timeout(self.timeout):
            return await call

    async def current(self, context, order_id):
        source = await self._call(self.journal.current(context, order_id))
        if source.subject_id != order_id or source.organization_id != context.organization_id:
            raise ConnectionError("invalid_source_binding")
        return preview(source, self.clock())

    async def submit(self, command: Command):
        try:
            result = await self._call(self.journal.reserve(command, conditions))
        except (TimeoutError, ConnectionError):
            # The journal may already have reserved or completed this exact action.
            return Operation(
                **command.model_dump(), state="pending", revision=command.expected_revision,
                pending_reason="response_unknown", next_actor="operator",
                responsible_operator_id=None, responsibility_revision=None, next_action="reconcile_transfer",
                next_review_at=self.clock() + timedelta(hours=24),
            )
        # A producer cannot acknowledge a different order, actor, quote or recipient.
        if any(getattr(result, name) != value for name, value in command.model_dump().items()):
            raise ConnectionError("invalid_operation_binding")
        return result

    def _scoped_result(self, result, context, operation_id):
        if (result.operation_id != operation_id or result.actor_id != context.actor_id
                or result.organization_id != context.organization_id):
            raise ConnectionError("invalid_operation_binding")
        return result

    async def lookup(self, context, operation_id):
        result = await self._call(self.journal.lookup(context, operation_id))
        return self._scoped_result(result, context, operation_id)

    async def recover(self, context, operation_id):
        result = await self._call(self.journal.reconcile(context, operation_id))
        return self._scoped_result(result, context, operation_id)
