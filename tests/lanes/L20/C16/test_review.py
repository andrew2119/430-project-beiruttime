import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
import pytest
from pydantic import ValidationError
from bt_contracts.eligibility.private_review.models import Actor, Command, Source
from l20_private_review.review import ReviewError, ReviewService, retention

FIXTURE = Path(__file__).resolve().parents[4]/'packages/contracts-eligibility/private-review/fixtures.json'
DATA = json.loads(FIXTURE.read_text())
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)
CASE = UUID(DATA['source']['case_id'])
REVIEWER = UUID(int=10)
OPERATOR = UUID(int=11)
NEXT = UUID(int=12)


class Store:
    def __init__(self):
        self.case, self.receipts, self.events, self.audits = None, {}, [], []
        self.lock = asyncio.Lock()
        self.fail_emit = False

    @asynccontextmanager
    async def transaction(self, case_id):
        assert case_id == CASE
        async with self.lock:
            before = copy.deepcopy((self.case, self.receipts, self.events, self.audits))
            try:
                yield self
            except BaseException:
                self.case, self.receipts, self.events, self.audits = before
                raise

    async def load(self):
        return copy.deepcopy(self.case)

    async def receipt(self, operation_id):
        return self.receipts.get(operation_id)

    async def save(self, case):
        self.case = copy.deepcopy(case)

    async def record(self, operation_id, actor_id, digest, result):
        self.receipts[operation_id] = {'actor_id': actor_id, 'digest': digest, 'result': copy.deepcopy(result)}

    async def emit(self, event):
        if self.fail_emit:
            raise RuntimeError('outbox unavailable')
        self.events.append(event)

    async def audit(self, actor_id, kind, clock):
        self.audits.append((actor_id, kind, clock))


class Authority:
    def __init__(self):
        self.source = Source.model_validate(DATA['source'])
        self.unavailable = False

    @asynccontextmanager
    async def fence(self, token, case_id):
        if self.unavailable:
            raise TimeoutError()
        actor_id = UUID(token)
        yield Actor(actor_id=actor_id, permissions=frozenset({'eligibility.identity.assign'} if actor_id == OPERATOR else {'eligibility.identity.review'}), active=True), self.source


@pytest.fixture
def context():
    store, authority = Store(), Authority()
    return store, authority, ReviewService(store, authority, lambda: NOW)


def command(source, kind, revision, assignment=1, operation=100, **kwargs):
    return Command(case_id=CASE, operation_id=UUID(int=operation), expected_revision=revision,
        assignment_revision=assignment, binding=source.binding, kind=kind, reason='Synthetic identity checked / تمت مراجعة الهوية التجريبية', **kwargs)


async def assigned(context):
    store, authority, service = context
    await service.command(str(OPERATOR), command(authority.source, 'reassign', 0, reviewer_id=REVIEWER))
    return store, authority, service


async def claimed(context):
    store, authority, service = await assigned(context)
    await service.command(str(REVIEWER), command(authority.source, 'claim', 1, operation=101))
    return store, authority, service


@pytest.mark.asyncio
async def test_identity_only_success_and_operation_lookup(context):
    store, authority, service = await claimed(context)
    action = command(authority.source, 'decide', 2, operation=102, verdict='eligible')
    result = await service.command(str(REVIEWER), action)
    assert result['state'] == 'eligible' and result['execution_authorized'] is False
    assert await service.read(str(REVIEWER), CASE, 'operation', operation_id=action.operation_id) == result
    assert (await service.read(str(REVIEWER), CASE, 'evidence'))['synthetic'] is True
    assert len(store.events) == 3
    assert 'reason' not in json.dumps(store.events)
    assert 'identity_match' not in json.dumps(store.events)


@pytest.mark.asyncio
@pytest.mark.parametrize('actor_id', [UUID(int=1), UUID(int=2), OPERATOR, UUID(int=99)])
async def test_buyer_brand_approver_operator_wrong_assignee_denied(context, actor_id):
    _, authority, service = await claimed(context)
    for kind in ['current', 'history', 'evidence']:
        with pytest.raises(ReviewError) as error:
            await service.read(str(actor_id), CASE, kind, operation_id=UUID(int=101))
        assert error.value.status == 403
    with pytest.raises(ReviewError) as error:
        await service.command(str(actor_id), command(authority.source, 'decide', 2, verdict='eligible'))
    assert error.value.status == 403


@pytest.mark.asyncio
async def test_reassignment_revokes_reads_decisions_and_receipts(context):
    _, authority, service = await claimed(context)
    await service.command(str(OPERATOR), command(authority.source, 'reassign', 2, operation=102, reviewer_id=NEXT))
    for kind in ['current', 'history', 'evidence', 'operation']:
        with pytest.raises(ReviewError, match='denied'):
            await service.read(str(REVIEWER), CASE, kind, operation_id=UUID(int=101))
    with pytest.raises(ReviewError, match='denied'):
        await service.command(str(REVIEWER), command(authority.source, 'decide', 3, assignment=2, verdict='eligible'))
    assert (await service.read(str(NEXT), CASE))['state'] == 'assigned'


@pytest.mark.asyncio
async def test_wrong_case_provider_fails_closed(context):
    _, authority, service = await claimed(context)
    authority.source = authority.source.model_copy(update={'case_id': UUID(int=999)})
    with pytest.raises(ReviewError, match='denied'):
        await service.read(str(REVIEWER), CASE, 'evidence')


@pytest.mark.asyncio
async def test_lost_response_duplicate_conflicting_retry_and_concurrent_retry(context):
    store, authority, service = await claimed(context)
    action = command(authority.source, 'decide', 2, operation=102, verdict='eligible')
    first, second = await asyncio.gather(service.command(str(REVIEWER), action), service.command(str(REVIEWER), action))
    assert first == second and len(store.case['history']) == 1 and len(store.events) == 3
    with pytest.raises(ReviewError, match='operation_conflict'):
        await service.command(str(REVIEWER), action.model_copy(update={'reason': 'Changed reason'}))


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['active_identity', 'active_business', 'active_consent', 'accepted_quote'])
async def test_revoked_or_missing_prerequisite_cannot_decide(context, change):
    store, authority, service = await claimed(context)
    authority.source = authority.source.model_copy(update={change: False})
    with pytest.raises(ReviewError):
        await service.command(str(REVIEWER), command(authority.source, 'decide', 2, operation=102, verdict='eligible'))
    assert not store.case['history']


@pytest.mark.asyncio
async def test_stale_source_and_revision_correction_and_new_claim(context):
    store, authority, service = await claimed(context)
    stale = command(authority.source, 'decide', 2, operation=102, verdict='eligible')
    authority.source = authority.source.model_copy(update={'binding': authority.source.binding.model_copy(update={'source_revision': 2})})
    assert (await service.read(str(REVIEWER), CASE))['state'] == 'invalidated'
    with pytest.raises(ReviewError, match='stale_source'):
        await service.command(str(REVIEWER), stale)
    with pytest.raises(ReviewError, match='stale_revision'):
        await service.command(str(REVIEWER), command(authority.source, 'claim', 1, operation=110))
    await service.command(str(REVIEWER), command(authority.source, 'claim', 2, operation=103))
    await service.command(str(REVIEWER), command(authority.source, 'correct', 3, operation=104))
    await service.command(str(REVIEWER), command(authority.source, 'claim', 4, operation=105))
    await service.command(str(REVIEWER), command(authority.source, 'decide', 5, operation=106, verdict='not_eligible'))
    assert [item['verdict'] for item in store.case['history']] == ['correction', 'not_eligible']


@pytest.mark.asyncio
async def test_timeout_and_atomic_outbox_failure_do_not_accept(context):
    store, authority, service = await claimed(context)
    action = command(authority.source, 'decide', 2, operation=102, verdict='eligible')
    authority.unavailable = True
    with pytest.raises(ReviewError, match='unavailable'):
        await service.command(str(REVIEWER), action)
    authority.unavailable = False
    store.fail_emit = True
    with pytest.raises(ReviewError, match='unavailable'):
        await service.command(str(REVIEWER), action)
    assert store.case['revision'] == 2 and action.operation_id not in store.receipts
    store.fail_emit = False
    assert (await service.command(str(REVIEWER), action))['state'] == 'eligible'


@pytest.mark.asyncio
async def test_objective_policy_and_minimal_evidence(context):
    _, authority, service = await claimed(context)
    authority.source = authority.source.model_copy(update={'evidence': authority.source.evidence.model_copy(update={'identity_match': 'unclear'})})
    with pytest.raises(ReviewError, match='objective_policy_failed'):
        await service.command(str(REVIEWER), command(authority.source, 'decide', 2, operation=102, verdict='eligible'))
    for field in ['income', 'wealth', 'document_bytes', 'payment_capacity']:
        body = copy.deepcopy(DATA['source'])
        body['evidence'][field] = 'synthetic'
        with pytest.raises(ValidationError):
            Source.model_validate(body)


@pytest.mark.asyncio
async def test_d31_retention_at_equality_obligation_hold_and_redaction(context):
    store, authority, service = await claimed(context)
    await service.command(str(REVIEWER), command(authority.source, 'decide', 2, operation=102, verdict='eligible'))
    assert 'evidence_deleted_at' not in retention(store.case, authority.source, NOW+timedelta(days=30)-timedelta(microseconds=1))
    held = authority.source.model_copy(update={'active_obligation': True})
    assert retention(store.case, held, NOW+timedelta(days=40)) == store.case
    store.case = retention(store.case, authority.source, NOW+timedelta(days=30))
    assert 'reason' not in store.case['history'][0]
    with pytest.raises(ReviewError, match='evidence_unavailable'):
        await service.read(str(REVIEWER), CASE, 'evidence')


@pytest.mark.asyncio
async def test_history_pagination_uses_server_total(context):
    store, _, service = await assigned(context)
    store.case['history'] = [{'review_revision': n} for n in range(1000)]
    page = await service.read(str(REVIEWER), CASE, 'history', page=40)
    assert page['total'] == 1000 and len(page['items']) == 25 and page['items'][-1]['review_revision'] == 999
    assert (await service.read(str(REVIEWER), CASE, 'history', page=41))['items'] == []


@pytest.mark.asyncio
async def test_invalidated_read_supplies_current_binding_for_new_claim(context):
    _, authority, service = await claimed(context)
    authority.source = authority.source.model_copy(update={'binding': authority.source.binding.model_copy(update={'source_revision': 2})})
    result = await service.read(str(REVIEWER), CASE)
    assert result['binding']['source_revision'] == 2
    action = command(authority.source, 'claim', result['revision'], operation=110)
    assert (await service.command(str(REVIEWER), action))['state'] == 'under_review'


@pytest.mark.asyncio
async def test_missing_evidence_allows_correction_but_never_verdict(context):
    _, authority, service = await claimed(context)
    authority.source = authority.source.model_copy(update={'evidence': None})
    with pytest.raises(ReviewError, match='evidence_missing'):
        await service.command(str(REVIEWER), command(authority.source, 'decide', 2, operation=110, verdict='eligible'))
    assert (await service.command(str(REVIEWER), command(authority.source, 'correct', 2, operation=111)))['state'] == 'correction'


@pytest.mark.asyncio
async def test_reopened_review_is_not_deleted_on_previous_final_deadline(context):
    store, authority, service = await claimed(context)
    await service.command(str(REVIEWER), command(authority.source, 'decide', 2, operation=102, verdict='eligible'))
    authority.source = authority.source.model_copy(update={'binding': authority.source.binding.model_copy(update={'source_revision': 2})})
    await service.command(str(REVIEWER), command(authority.source, 'claim', 3, operation=110))
    assert retention(store.case, authority.source, NOW+timedelta(days=30)) == store.case


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'organization_id': UUID(int=99)}, {'active': False}, {'permissions': frozenset()},
])
async def test_current_actor_scope_and_permission_revocation(context, change):
    store, authority, service = await claimed(context)
    @asynccontextmanager
    async def changed(token, case_id):
        actor = Actor(actor_id=REVIEWER, permissions=frozenset({'eligibility.identity.review'}), active=True)
        yield actor.model_copy(update=change), authority.source
    authority.fence = changed
    with pytest.raises(ReviewError, match='denied'):
        await service.read(str(REVIEWER), CASE, 'evidence')
    with pytest.raises(ReviewError, match='denied'):
        await service.command(str(REVIEWER), command(authority.source, 'decide', 2, operation=110, verdict='eligible'))
    assert not store.case['history']
