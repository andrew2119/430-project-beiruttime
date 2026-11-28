"""Owner selection publishes only validated released history entries."""
import asyncio
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Publication:
    operation_id: UUID
    actor_id: UUID
    subject_id: UUID
    organization_id: UUID | None
    watch_id: UUID
    expected_revision: int
    job_ids: tuple[UUID, ...]

    def __post_init__(self):
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError('Invalid revision')
        if len(self.job_ids) > 50 or len(set(self.job_ids)) != len(self.job_ids):
            raise ValueError('Invalid selection')


async def publish(provider, reader, read, command: Publication):
    """Commit rechecks current ownership/revision atomically with the receipt.

    The provider stores only the supplied validated entry snapshots. A conflicting
    duplicate denies, a matching one returns its durable original result. Empty
    selection withdraws publication. The provider owns the serialized source lock.
    """
    def envelope(state, revision=None):
        return reader.contract.PublicationResult(**read.__dict__, state=state, revision=command.expected_revision if revision is None else revision, total=0, next_actor='record_operator' if state in ('pending', 'unavailable') else 'reader', pending_reason='source_pending' if state=='pending' else 'source_unavailable' if state=='unavailable' else None).model_dump(mode='json')
    result = envelope('denied')
    if (read.operation_id != command.operation_id or read.actor_id != command.actor_id or read.subject_id != command.subject_id
            or read.organization_id != command.organization_id or read.watch_id != command.watch_id
            or read.expected_revision != command.expected_revision):
        return result
    try:
        async with asyncio.timeout(2):
            if not await provider.current_owner(command):
                return result
            stored = await provider.lookup_publication(command.operation_id, command.actor_id)
            if stored is not None:
                previous, receipt = stored
                if previous != command:
                    return result
                saved = reader.contract.PublicationResult.model_validate(receipt)
                if (saved.operation_id != command.operation_id or saved.actor_id != command.actor_id
                        or saved.subject_id != command.subject_id or saved.watch_id != command.watch_id
                        or saved.organization_id != command.organization_id
                        or saved.expected_revision != command.expected_revision):
                    return result
                return saved.model_dump(mode='json')
            entries = []
            for job_id in command.job_ids:
                # Exact job lookup must recheck current permission and completion,
                # with a fixed result bound, rather than scan arbitrary pages.
                entry = await provider.safe_released_job(read, job_id)
                safe = reader.contract.Entry.model_validate(entry)
                if safe.job_id != job_id or safe.watch_id != command.watch_id:
                    return result
                if read.organization_id and safe.organization_id != read.organization_id:
                    return result
                if safe.source_revision > command.expected_revision:
                    return envelope('stale')
                entries.append(safe.model_dump(mode='json'))
            try:
                receipt = await provider.commit_publication(command, entries)
                return envelope(receipt['state'], receipt.get('revision', command.expected_revision))
            except (ValueError, KeyError, TypeError):
                return envelope('pending')
    except (TimeoutError, OSError):
        return envelope('pending')
    except (ValueError, KeyError, TypeError):
        return result


async def lookup_publication(provider, reader, operation_id, context):
    async with asyncio.timeout(2):
        stored = await provider.lookup_publication(operation_id, context.actor_id)
        if stored is None:
            return None
        command, receipt = stored
        if (command.actor_id != context.actor_id or command.subject_id != context.subject_id
                or command.organization_id != context.organization_id
                or not await provider.current_owner(command)):
            return None
        read = reader.contract.PublicationResult.model_validate(receipt)
        if (read.operation_id != operation_id or read.actor_id != context.actor_id
                or read.subject_id != context.subject_id or read.organization_id != context.organization_id
                or read.watch_id != command.watch_id):
            return None
        return read
