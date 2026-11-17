"""Bounded reads over current authoritative release and permission facts."""
import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class Read:
    operation_id: UUID
    actor_id: UUID
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID | None
    expected_revision: int
    page: int = 0
    page_size: int = 20

    def __post_init__(self):
        if type(self.page) is not int or type(self.page_size) is not int or not 0 <= self.page <= 10000 or not 1 <= self.page_size <= 50:
            raise ValueError('Invalid page')
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError('Invalid revision')


@dataclass(frozen=True)
class Scope:
    allowed: bool
    revision: int


@dataclass(frozen=True)
class Source:
    revision: int
    settled: bool
    total: int
    rows: tuple[dict, ...]


class Provider(Protocol):
    async def authorize(self, read: Read) -> Scope: ...
    async def remember(self, read: Read) -> bool:
        """Atomically persist exact binding; identical duplicate returns true."""
        ...
    async def lookup(self, operation_id: UUID, actor_id: UUID) -> Read | None: ...
    async def current_owner(self, command) -> bool:
        """Check live owner, actor, subject and selected business scope."""
        ...
    async def safe_released_job(self, read: Read, job_id: UUID) -> dict:
        """Return only reviewed safe fields from actual released completed work."""
        ...
    async def commit_publication(self, command, entries: list[dict]) -> dict:
        """Atomically recheck owner, scope, revision and each current release fact.

        Replace the safe subset and store a fully bound durable result together.
        Identical duplicate returns its result; conflicting duplicate denies.
        Never accept a stale snapshot or a new rework fact as completed work.
        """
        ...
    async def lookup_publication(self, operation_id: UUID, actor_id: UUID):
        """Return persisted command and versioned result, never private evidence."""
        ...
    async def released(self, read: Read) -> Source:
        """Page only released completed work, with total and current revision."""
        ...


class Reader:
    def __init__(self, provider: Provider, contract):
        self.provider = provider
        self.contract = contract

    async def lookup(self, operation_id, actor_id, subject_id, organization_id):
        try:
            read = await asyncio.wait_for(self.provider.lookup(operation_id, actor_id), 2)
        except OSError:
            raise TimeoutError() from None
        if (read is None or read.actor_id != actor_id or read.subject_id != subject_id
                or read.organization_id != organization_id):
            return None
        return await self.read(read)

    async def read(self, read: Read):
        def result(state, revision=0, items=(), total=0):
            return self.contract.Result(**read.__dict__, state=state, revision=revision,
                items=items, total=total, next_actor='reader' if state in ('ready', 'stale', 'denied') else 'record_operator',
                pending_reason='source_pending' if state == 'pending' else 'source_unavailable' if state == 'unavailable' else None)
        try:
            async with asyncio.timeout(2):
                scope = await self.provider.authorize(read)
                if not scope.allowed:
                    return result('denied')
                if scope.revision != read.expected_revision:
                    return result('stale', scope.revision)
                if not await self.provider.remember(read):
                    return result('denied')
                source = await self.provider.released(read)
                if source.revision != scope.revision:
                    return result('stale', source.revision)
                if not source.settled:
                    return result('pending', source.revision)
                if len(source.rows) > read.page_size or source.total < len(source.rows):
                    return result('unavailable')
                entries = []
                for row in source.rows:
                    if row['state'] != 'released_completed' or row['actual_work'] is not True or row['current_quality'] != 'passed':
                        return result('unavailable')
                    if row['privacy_reviewed'] is not True:
                        return result('unavailable')
                    fields = {key: row[key] for key in ('job_id', 'watch_id', 'organization_id', 'kind', 'work_codes', 'released_at', 'source_revision', 'warranty')}
                    entry = self.contract.Entry(**fields)
                    if entry.watch_id != read.watch_id or entry.source_revision > source.revision:
                        return result('unavailable')
                    if read.organization_id and entry.organization_id != read.organization_id:
                        return result('denied')
                    entries.append(entry)
                # Revocation or late mutation during the read must clear the response.
                current = await self.provider.authorize(read)
                if not current.allowed:
                    return result('denied')
                if current.revision != source.revision:
                    return result('stale', current.revision)
                return result('ready', source.revision, tuple(entries), source.total)
        except (TimeoutError, OSError, ValueError, KeyError, TypeError):
            return result('unavailable')
