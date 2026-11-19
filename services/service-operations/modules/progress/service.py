import asyncio
import hashlib
from datetime import datetime, timezone
from .contracts import Source
from .model import Denied, authorize, validate, project
from .store import decoded


async def current(provider, access, subject_id):
    try:
        async with asyncio.timeout(1.2):
            source = Source.model_validate(await provider(access, subject_id))
        if source.subject_id != subject_id:
            raise ValueError('Subject mismatch')
        return source
    except (TimeoutError, ConnectionError, ValueError, TypeError, KeyError):
        raise Denied('unavailable', 503) from None


async def execute(store, provider, access, command, clock=lambda: datetime.now(timezone.utc)):
    await store.lock(command.subject_id, command.operation_id)
    source = await current(provider, access, command.subject_id)
    now = clock()
    authorize(access, source, now, write=True)
    digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    prior = await store.receipt(command.operation_id)
    authorize(access, source, clock(), write=True)
    if prior:
        if (prior['actor_id'] != access.actor_id or prior['organization_id'] != access.organization_id
                or prior['subject_id'] != command.subject_id or prior['request_hash'] != digest):
            raise Denied('operation_conflict')
        return decoded(prior['result'])
    revision, reports = await store.job(command.subject_id)
    validate(command, source, access, revision, now)
    old = reports.get(str(command.line_id))
    since = old['since_at'] if old and old['state'] == command.state and old['scope_revision'] == command.scope_revision else now.isoformat()
    report = {**command.model_dump(mode='json'), 'actor_id': str(access.actor_id), 'recorded_at': now.isoformat(),
              'since_at': since, 'next_review_at': command.next_review_at.isoformat()}
    reports = {**reports, str(command.line_id): report}
    result = dict(schema_version='service.progress.v1', operation_id=str(command.operation_id),
                  subject_id=str(command.subject_id), watch_id=str(command.watch_id), actor_id=str(access.actor_id),
                  organization_id=str(command.organization_id), expected_revision=command.expected_revision,
                  state='acknowledged', revision=revision + 1, pending_reason=None,
                  next_actor=str(command.next_actor), next_review_at=command.next_review_at.isoformat())
    # Revalidate the short authority lease immediately before writing.
    authorize(access, source, clock(), write=True)
    await store.save(command, access, report, reports, result, digest)
    authorize(access, source, clock(), write=True)
    return result


async def read(store, provider, access, subject_id, offset, clock=lambda: datetime.now(timezone.utc)):
    source = await current(provider, access, subject_id)
    authorize(access, source, clock())
    revision, reports = await store.job(subject_id)
    authorize(access, source, clock())
    return project(source, reports, revision, clock(), offset)
