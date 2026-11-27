"""Assigned review transitions; persistence and current authority are explicit ports."""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from typing import Protocol
from uuid import UUID
from bt_contracts.eligibility.private_review.models import Actor, Command, Decision, Source


class ReviewError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


class Authority(Protocol):
    def fence(self, token: str, case_id: UUID):
        """Yield current Actor/Source; serialize invalidation until the context exits."""
        ...


class Repository(Protocol):
    def transaction(self, case_id: UUID):
        """Yield a locked transaction with load/save/audit/outbox methods."""
        ...


def now_utc():
    return datetime.now(timezone.utc)


def independent(actor_id, source):
    return actor_id not in {source.binding.subject_id, source.brand_approver_id}


def access(actor, source, case, *, operator=False):
    if not actor.active or not source.active_identity or not source.active_business:
        raise ReviewError(403, 'denied')
    if actor.organization_id is not None and actor.organization_id != source.binding.organization_id:
        raise ReviewError(403, 'denied')
    if not independent(actor.actor_id, source):
        raise ReviewError(403, 'denied')
    if operator:
        if 'eligibility.identity.assign' not in actor.permissions:
            raise ReviewError(403, 'denied')
    elif (not case or case['reviewer_id'] != str(actor.actor_id)
          or actor.actor_id not in source.eligible_reviewers
          or 'eligibility.identity.review' not in actor.permissions):
        raise ReviewError(403, 'denied')


def current(case, source):
    if (case['binding'] != source.binding.model_dump(mode='json')
            or not source.active_consent or not source.accepted_quote):
        return 'invalidated'
    return case['state']


def reference(case, source, actor_id, expected_revision=None):
    return {key: case[key] for key in ('case_id', 'reviewer_id', 'revision', 'assignment_revision')} | {
        'schema_version': 'eligibility.private-review.v1', 'state': current(case, source),
        'binding': source.binding.model_dump(mode='json'), 'execution_authorized': False,
        'operation_id': None, 'actor_id': str(actor_id),
        'subject_id': str(source.binding.subject_id), 'watch_id': str(source.binding.watch_id),
        'organization_id': str(source.binding.organization_id),
        'expected_revision': case['revision'] if expected_revision is None else expected_revision,
        'pending_reason': 'source_changed' if current(case, source) == 'invalidated' else None,
        'next_actor': case['reviewer_id'], 'next_review_at': None,
    }


def apply(case, command, actor, source, clock):
    assigning = command.kind == 'reassign'
    access(actor, source, case, operator=assigning)
    if command.binding != source.binding:
        raise ReviewError(409, 'stale_source')
    if not source.active_consent or not source.accepted_quote:
        raise ReviewError(409, 'prerequisites_missing')
    revision = case['revision'] if case else 0
    assignment = case['assignment_revision'] if case else 1
    if command.expected_revision != revision or command.assignment_revision != assignment:
        raise ReviewError(409, 'stale_revision')
    if command.kind != 'decide' and command.verdict is not None:
        raise ReviewError(422, 'invalid_verdict')
    if assigning:
        target = command.reviewer_id
        if target not in source.eligible_reviewers or not independent(target, source):
            raise ReviewError(403, 'independence_required')
        if case and str(target) == case['reviewer_id']:
            raise ReviewError(409, 'already_assigned')
        case = dict(case or {'case_id': str(command.case_id), 'history': [], 'created_at': clock.isoformat()})
        case.update(reviewer_id=str(target), assignment_revision=assignment + (1 if revision else 0), state='assigned', final_review_at=None)
    else:
        if command.reviewer_id is not None:
            raise ReviewError(422, 'invalid_reviewer')
        case = dict(case)
        if command.kind == 'claim':
            if current(case, source) not in {'assigned', 'correction', 'invalidated'}:
                raise ReviewError(409, 'claim_required')
            case['state'] = 'under_review'
            case['final_review_at'] = None
        else:
            if current(case, source) != 'under_review':
                raise ReviewError(409, 'claim_required')
            if case.get('evidence_deleted_at'):
                raise ReviewError(409, 'evidence_unavailable')
            if command.kind == 'decide' and source.evidence is None:
                raise ReviewError(409, 'evidence_missing')
            verdict = command.verdict if command.kind == 'decide' else 'correction'
            if verdict is None:
                raise ReviewError(422, 'verdict_required')
            if verdict == 'eligible' and (source.evidence.identity_match != 'match' or not source.evidence.document_valid):
                raise ReviewError(409, 'objective_policy_failed')
            decision = Decision(operation_id=command.operation_id, actor_id=actor.actor_id,
                reviewer_id=actor.actor_id, assignment_revision=assignment, review_revision=revision+1,
                binding=source.binding, verdict=verdict, reason=command.reason, reviewed_at=clock)
            case['history'] = [*case['history'], decision.model_dump(mode='json')]
            case['state'] = verdict
            case['final_review_at'] = None if verdict == 'correction' else clock.isoformat()
    case.update(binding=source.binding.model_dump(mode='json'), revision=revision+1)
    return case


class ReviewService:
    def __init__(self, repository: Repository, authority: Authority, clock=now_utc):
        self.repository, self.authority, self.clock = repository, authority, clock

    @asynccontextmanager
    async def _transaction(self, token, case_id):
        try:
            async with asyncio.timeout(1.2):
                async with self.authority.fence(token, case_id) as (actor, source):
                    source = Source.model_validate(source)
                    actor = Actor.model_validate(actor)
                    if source.case_id != case_id:
                        raise ReviewError(403, 'denied')
                    async with self.repository.transaction(case_id) as tx:
                        yield tx, actor, source
        except ReviewError:
            raise
        except Exception:
            raise ReviewError(503, 'unavailable') from None

    async def command(self, token, command: Command):
        async with self._transaction(token, command.case_id) as (tx, actor, source):
            case = await tx.load()
            access(actor, source, case, operator=command.kind == 'reassign')
            digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
            prior = await tx.receipt(command.operation_id)
            if prior:
                if prior['actor_id'] != str(actor.actor_id) or prior['digest'] != digest:
                    raise ReviewError(409, 'operation_conflict')
                return prior['result']
            case = apply(case, command, actor, source, self.clock())
            result = reference(case, source, actor.actor_id, command.expected_revision) | {'operation_id': str(command.operation_id)}
            await tx.save(case)
            await tx.record(command.operation_id, str(actor.actor_id), digest, result)
            # No evidence, reason, subject, quote or verdict leaves the private boundary.
            await tx.emit({'schema_version': 'eligibility.private-review-changed.v1',
                'case_id': str(command.case_id), 'revision': case['revision']})
            return result

    async def read(self, token, case_id, kind='current', page=1, operation_id=None):
        if not 1 <= page <= 1000000:
            raise ReviewError(422, 'invalid_page')
        async with self._transaction(token, case_id) as (tx, actor, source):
            case = await tx.load()
            operator_lookup = kind == 'operation' and 'eligibility.identity.assign' in actor.permissions
            access(actor, source, case, operator=operator_lookup)
            await tx.audit(str(actor.actor_id), kind, self.clock())
            if kind == 'evidence':
                if current(case, source) == 'invalidated' or not source.evidence or case.get('evidence_deleted_at'):
                    raise ReviewError(409, 'evidence_unavailable')
                return source.evidence.model_dump(mode='json')
            if kind == 'history':
                return {'items': case['history'][(page-1)*25:page*25], 'total': len(case['history']), 'page': page, 'page_size': 25}
            if kind == 'operation':
                receipt = await tx.receipt(operation_id)
                if not receipt or receipt['actor_id'] != str(actor.actor_id):
                    raise ReviewError(404, 'not_found')
                return receipt['result']
            return reference(case, source, actor.actor_id)


def retention(case, source: Source, clock: datetime, deletion_requested_at=None):
    """Return a redacted copy; the scheduler persists this inside the same transaction."""
    if source.active_obligation:
        return case
    result = dict(case)
    final = case.get('final_review_at')
    created = datetime.fromisoformat(case['created_at'])
    if not final and not deletion_requested_at:
        return case
    due = datetime.fromisoformat(final) + timedelta(days=30) if final else deletion_requested_at + timedelta(days=30)
    if deletion_requested_at:
        due = min(due, deletion_requested_at + timedelta(days=30))
    if clock >= due:
        result['history'] = [{k: v for k, v in item.items() if k != 'reason'} for item in case['history']]
        result['evidence_deleted_at'] = clock.isoformat()
    result['minimal_references_due_at'] = (created + timedelta(days=365)).isoformat()
    return result
