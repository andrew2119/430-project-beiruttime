"""Repair scope, explicit fees and transaction recovery without connected providers."""
from contextlib import asynccontextmanager
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID
import pytest
from pydantic import ValidationError
from bt_contracts_core.errors import PublicError, AccessDenied
from bt_contracts.pricing.quotes.assessed import AcceptQuote, DeclineQuote, IssueQuote
from conftest import load

policy = load('repair_policy', 'packages/contracts-pricing/repair-quotes/policy.py')
routes = load('repair_routes', 'services/pricing/modules/repair-quotes/routes.py')
ROOT = Path(__file__).resolve().parents[4]
FIXTURE = json.loads((ROOT / 'packages/contracts-pricing/repair-quotes/fixtures/assessed.v1.json').read_text())
NOW = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
BUYER = UUID(FIXTURE['expected']['buyer_id'])
QUOTE = UUID('00000000-0000-4000-8000-000000000010')


def snapshot():
    return {**copy.deepcopy(FIXTURE['issue']), 'id': str(QUOTE), 'kind': 'repair', 'revision': 1,
            'buyer_id': str(BUYER), 'organization_id': FIXTURE['expected']['organization_id'],
            'diagnosis': 'Worn seal', 'terms_digest': 'a' * 64, 'policy': {'revision': 2}}


def source(s):
    return {**{k: s[k] for k in ['buyer_id', 'organization_id', 'diagnosis']},
            'lines': [{k: v for k, v in line.items() if k != 'amount_minor'} for line in s['lines']]}


def row():
    return {'id': QUOTE, 'kind': 'repair', 'revision': 1, 'buyer_id': BUYER,
            'source_id': UUID(FIXTURE['issue']['source_id']), 'state': 'issued',
            'expires_at': NOW + timedelta(minutes=15), 'snapshot': snapshot()}


def test_contract_and_exact_job_economics():
    issue = IssueQuote.model_validate(FIXTURE['issue'])
    command = AcceptQuote.model_validate(FIXTURE['accept'])
    assert issue.currency == 'USD'
    totals = routes.amounts(snapshot()['lines'], [str(v) for v in command.selected_line_ids], issue.assessment_fee_minor)
    assert totals['payable_minor'] == 11000
    assert totals['platform_fee_minor'] == totals['seller_commission_minor'] == 550
    assert totals['seller_net_minor'] == 10450
    assert sum([totals['seller_net_minor'], totals['platform_fee_minor']]) == totals['payable_minor']


@pytest.mark.parametrize('field,value', [('payable_minor', True), ('payable_minor', 1.5),
    ('payable_minor', float('inf')), ('selected_line_ids', []), ('accept_assessment_fee', 1)])
def test_command_bounds(field, value):
    with pytest.raises(ValidationError):
        AcceptQuote.model_validate({**FIXTURE['accept'], field: value})


@pytest.mark.parametrize('field,value', [('mandatory', False), ('part_reference', 'OTHER'),
    ('label', 'New diagnosed part'), ('kind', 'labor')])
def test_changed_line_requires_renewed_quote(field, value):
    s = snapshot()
    current = source(s)
    current['lines'][0][field] = value
    with pytest.raises(PublicError):
        policy.current_scope(s, current)


@pytest.mark.parametrize('field', ['diagnosis', 'buyer_id', 'organization_id'])
def test_changed_diagnosis_or_party_denies(field):
    s = snapshot()
    current = source(s)
    current[field] = 'changed'
    with pytest.raises(PublicError):
        policy.current_scope(s, current)


def test_unchanged_scope_accepts_order_independent_lines():
    s = snapshot()
    current = source(s)
    current['lines'].reverse()
    policy.current_scope(s, current)


@pytest.mark.parametrize('delta,allowed', [(-1, True), (0, False), (1, False)])
def test_acceptance_boundary(delta, allowed):
    r = row()
    args = (r, r['snapshot'], AcceptQuote.model_validate(FIXTURE['accept']))
    now = r['expires_at'] + timedelta(microseconds=delta)
    if allowed:
        policy.decision_binding(*args, accepting=True, now=now)
    else:
        with pytest.raises(PublicError):
            policy.decision_binding(*args, accepting=True, now=now)
    policy.decision_binding(r, r['snapshot'], DeclineQuote.model_validate(FIXTURE['decline']), accepting=False, now=now)


@pytest.mark.parametrize('patch', [{'quote_revision': 2}, {'terms_digest': 'b' * 64},
                                   {'accept_assessment_fee': False}])
def test_stale_or_unaccepted_fee_denied(patch):
    r = row()
    body = AcceptQuote.model_validate({**FIXTURE['accept'], **patch})
    with pytest.raises(PublicError):
        policy.decision_binding(r, r['snapshot'], body, accepting=True, now=NOW)


class Transaction:
    def __init__(self, r):
        self.row = r
        self.fetchval = AsyncMock(return_value=NOW)
        self.execute = AsyncMock()
        self.fetchrow = AsyncMock(side_effect=self.result)

    async def result(self, sql, *args):
        if sql.startswith('UPDATE'):
            self.row['state'] = args[1]
            return self.row
        return {'decision': self.row['state']}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def seam(monkeypatch):
    r = row()
    tx = Transaction(r)
    receipts = {}
    async def replay(_tx, p, key, fingerprint):
        if key in receipts:
            old, result = receipts[key]
            if old != fingerprint:
                raise PublicError('idempotency_conflict', 'Changed operation.', status=409)
            return result
    async def remember(_tx, p, key, fingerprint, result):
        result = {'operation_id': 'retained-operation', **result}
        receipts[key] = (fingerprint, result)
        return result
    @asynccontextmanager
    async def authorization(*args):
        yield source(r['snapshot'])
    @asynccontextmanager
    async def assigned(request, principal, snapshot, key):
        yield {'schema_version': 1, 'assignment_id': QUOTE, 'assignment_revision': 1,
               'operator_id': UUID('00000000-0000-4000-8000-000000000099'),
               'quote_id': QUOTE, 'buyer_id': BUYER,
               'organization_id': UUID(snapshot['organization_id']), 'operation_id': key}
    monkeypatch.setattr(routes, 'recovery_assignment', assigned)
    monkeypatch.setattr(routes, 'source_authorization', authorization)
    monkeypatch.setattr(routes, 'unit_of_work', lambda pool: tx)
    monkeypatch.setattr(routes, 'load', AsyncMock(return_value=r))
    monkeypatch.setattr(routes, 'replay', replay)
    monkeypatch.setattr(routes, 'remember', remember)
    monkeypatch.setattr(routes, 'current_source', AsyncMock(return_value=source(r['snapshot'])))
    monkeypatch.setattr(routes, 'event', AsyncMock())
    monkeypatch.setattr(routes, 'recovery_event', AsyncMock())
    monkeypatch.setattr(routes, 'project', lambda row, decision: {'state': row['state']})
    p = SimpleNamespace(actor=SimpleNamespace(subject_id=BUYER, organization_id=None), roles=['buyer'])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    return r, tx, p, request


@pytest.mark.asyncio
async def test_lost_response_replay_and_changed_retry(seam):
    r, tx, p, request = seam
    body = AcceptQuote.model_validate(FIXTURE['accept'])
    first = await routes.decide(QUOTE, body, request, p, 'repair-once', accepting=True)
    second = await routes.decide(QUOTE, body, request, p, 'repair-once', accepting=True)
    assert first == second
    assert tx.execute.await_count == 2  # Scope lock and one decision insert.
    assert routes.event.await_count == 1
    with pytest.raises(PublicError):
        await routes.decide(QUOTE, body.model_copy(update={'payable_minor': 1}), request, p, 'repair-once', accepting=True)


@pytest.mark.asyncio
async def test_decline_after_expiry_does_not_need_diagnosis_or_collect(seam):
    r, tx, p, request = seam
    tx.fetchval.return_value = r['expires_at']
    routes.current_source.side_effect = RuntimeError('unavailable')
    result = await routes.decide(QUOTE, DeclineQuote.model_validate(FIXTURE['decline']), request, p, 'repair-decline', accepting=False)
    assert result['quote']['state'] == 'declined_return_held'
    routes.current_source.assert_not_awaited()
    inserted = tx.execute.call_args_list[1].args
    assert json.loads(inserted[4]) == []
    assert json.loads(inserted[5]) == {}
    assert json.loads(inserted[8]) == {'assessment': False, 'return_transport': False}


@pytest.mark.asyncio
async def test_dependency_timeout_writes_nothing(seam):
    _, tx, p, request = seam
    routes.current_source.side_effect = PublicError('dependency_unavailable', 'Unavailable.', status=503)
    with pytest.raises(PublicError):
        await routes.decide(QUOTE, AcceptQuote.model_validate(FIXTURE['accept']), request, p, 'repair-timeout', accepting=True)
    tx.execute.assert_not_awaited()
    routes.event.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_buyer_and_business_cannot_decide(seam):
    _, tx, p, request = seam
    p.actor.subject_id = UUID('00000000-0000-4000-8000-000000000099')
    with pytest.raises(AccessDenied):
        await routes.decide(QUOTE, AcceptQuote.model_validate(FIXTURE['accept']), request, p, 'repair-denied', accepting=True)
    p.actor.subject_id = BUYER
    p.actor.organization_id = UUID(FIXTURE['expected']['organization_id'])
    with pytest.raises(AccessDenied):
        await routes.decide(QUOTE, AcceptQuote.model_validate(FIXTURE['accept']), request, p, 'repair-denied', accepting=True)
    tx.execute.assert_not_awaited()


def test_route_replacements_are_unique():
    paths = [(route.path, method) for route in routes.router.routes for method in route.methods]
    assert paths.count(('/v1/repair-quotes/{quote_id}/accept', 'POST')) == 1
    assert paths.count(('/v1/repair-quotes/{quote_id}/decline', 'POST')) == 1
    assert paths.count(('/v1/repair-quotes', 'GET')) == 1
    assert paths.count(('/v1/repair-quotes/{quote_id}', 'GET')) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('page,total,count', [(1, 0, 0), (1, 1, 1), (1, 1000, 20), (50, 1000, 20), (51, 1000, 0)])
async def test_page_adapter_binds_offset_and_server_total(monkeypatch, page, total, count):
    r = row()
    serialized = {**r, 'id': str(QUOTE), 'source_id': str(r['source_id']), 'buyer_id': str(BUYER),
                  'expires_at': r['expires_at'].isoformat()}
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value={'rows': [serialized.copy() for _ in range(count)], 'total': total}),
                         fetch=AsyncMock(return_value=[]))
    class Pool:
        def acquire(self):
            class Context:
                async def __aenter__(self):
                    return tx
                async def __aexit__(self, *args):
                    return False
            return Context()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=Pool())))
    p = SimpleNamespace(actor=SimpleNamespace(subject_id=BUYER, organization_id=None), roles=['buyer'])
    monkeypatch.setattr(routes, 'project', lambda r, d: {'id': r['id'], 'state': r['state']})
    result = await routes.listing(request, page=page, p=p)
    assert result['total'] == total and result['page'] == page and result['page_size'] == 20
    assert len(result['items']) == count
    assert tx.fetchrow.call_args.args[1:] == (BUYER, None, (page - 1) * 20)


@pytest.mark.asyncio
async def test_http_adapter_rejects_bad_pages_and_malformed_consent(seam):
    import httpx
    from fastapi import FastAPI
    _, tx, p, _ = seam
    app = FastAPI()
    app.include_router(routes.router)
    async def principal():
        return p
    async def operation_key():
        return 'repair-invalid'
    app.dependency_overrides[routes.peers.principal] = principal
    app.dependency_overrides[routes.idempotency] = operation_key
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for page in ['0', '-1', '1000001', 'one']:
            assert (await client.get('/v1/repair-quotes?page=' + page)).status_code == 422
        bad = {**FIXTURE['accept'], 'accept_assessment_fee': 'yes'}
        response = await client.post('/v1/repair-quotes/' + str(QUOTE) + '/accept', json=bad,
                                     headers={'Idempotency-Key': 'repair-invalid'})
        assert response.status_code == 422
    tx.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_changes_after_preflight_before_persistence(seam, monkeypatch):
    r, tx, p, request = seam
    @asynccontextmanager
    async def changed(*args):
        current = source(r['snapshot'])
        current['diagnosis'] = 'Changed after preflight'
        yield current
    monkeypatch.setattr(routes, 'source_authorization', changed)
    with pytest.raises(PublicError):
        await routes.decide(QUOTE, AcceptQuote.model_validate(FIXTURE['accept']), request, p, 'repair-race', accepting=True)
    routes.current_source.assert_awaited_once()
    tx.execute.assert_not_awaited()
    routes.event.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_serialized_authorization_denies_without_write(seam, monkeypatch):
    _, tx, p, request = seam
    original = load('repair_routes_unavailable', 'services/pricing/modules/repair-quotes/routes.py')
    monkeypatch.setattr(routes, 'source_authorization', original.source_authorization)
    with pytest.raises(PublicError) as error:
        await routes.decide(QUOTE, AcceptQuote.model_validate(FIXTURE['accept']), request, p, 'repair-no-fence', accepting=True)
    assert error.value.code == 'dependency_unavailable'
    tx.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_decline_persists_recovery_and_retry_keeps_deadlines(seam):
    _, tx, p, request = seam
    body = DeclineQuote.model_validate(FIXTURE['decline'])
    first = await routes.decide(QUOTE, body, request, p, 'return-once', accepting=False)
    writes = [call for call in tx.execute.call_args_list if 'SET repair_recovery' in call.args[0]]
    assert len(writes) == 1
    record = json.loads(writes[0].args[2])
    assert record['operation_id'] == 'return-once'
    assert record['operator_id'].endswith('0099')
    assert record['next_action'] == 'arrange_controlled_unrepaired_return'
    assert datetime.fromisoformat(record['next_review_at']) == NOW + timedelta(hours=24)
    assert datetime.fromisoformat(record['escalate_at']) == NOW + timedelta(hours=48)
    assert routes.recovery_event.call_args.args[-1] == record
    tx.fetchval.return_value = NOW + timedelta(days=2)
    assert await routes.decide(QUOTE, body, request, p, 'return-once', accepting=False) == first
    assert tx.execute.await_count == 3


@pytest.mark.asyncio
async def test_missing_return_assignment_writes_nothing(seam, monkeypatch):
    _, tx, p, request = seam
    original = load('repair_recovery_unavailable', 'services/pricing/modules/repair-quotes/routes.py')
    monkeypatch.setattr(routes, 'recovery_assignment', original.recovery_assignment)
    with pytest.raises(PublicError) as error:
        await routes.decide(QUOTE, DeclineQuote.model_validate(FIXTURE['decline']), request, p,
                            'return-unavailable', accepting=False)
    assert error.value.code == 'dependency_unavailable'
    tx.execute.assert_not_awaited()
    routes.event.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_quote_return_assignment_writes_nothing(seam, monkeypatch):
    _, tx, p, request = seam
    @asynccontextmanager
    async def wrong(*args):
        yield {'schema_version': 1, 'assignment_id': QUOTE, 'assignment_revision': 1,
               'operator_id': QUOTE, 'quote_id': BUYER, 'buyer_id': BUYER,
               'organization_id': UUID(FIXTURE['expected']['organization_id']),
               'operation_id': 'return-wrong'}
    monkeypatch.setattr(routes, 'recovery_assignment', wrong)
    with pytest.raises(PublicError):
        await routes.decide(QUOTE, DeclineQuote.model_validate(FIXTURE['decline']), request, p,
                            'return-wrong', accepting=False)
    tx.execute.assert_not_awaited()


def test_recovery_projection_survives_read(monkeypatch):
    monkeypatch.setattr(routes, 'project', lambda row, decision: {'state': 'declined_return_held'})
    assert routes.repair_projection({}, {'repair_recovery': '{"operator_id":"retained"}'})['recovery'] == {'operator_id': 'retained'}


@pytest.mark.asyncio
async def test_recovery_outbox_uses_owned_event_schema(monkeypatch):
    enqueue = AsyncMock()
    monkeypatch.setattr(routes, 'enqueue', enqueue)
    request = SimpleNamespace(state=SimpleNamespace(request_id=str(QUOTE)))
    fixture = json.loads((ROOT / 'packages/contracts-pricing/repair-quotes/fixtures/return-recovery.v1.json').read_text())
    assignment = routes.recovery.RecoveryAssignment.model_validate_json(json.dumps(fixture['assignment']))
    record = routes.recovery.recovery_record(assignment, NOW)
    await routes.recovery_event(None, request, row(), record)
    envelope = enqueue.call_args.args[1]
    assert envelope.type == 'pricing.repair-return.recovery-required.v1'
    assert envelope.data['next_review_at'] == fixture['next_review_at']
    assert envelope.data['escalate_at'] == fixture['escalate_at']
    assert enqueue.call_args.args[2] == ['repair-return-recovery-v1']
    with pytest.raises(ValidationError):
        routes.recovery.RecoveryAssignment.model_validate_json(json.dumps({**fixture['assignment'], 'assignment_revision': 0}))


@pytest.mark.parametrize('delta,expired', [(-1, False), (0, True), (1, True)])
def test_expiry_projection_never_invents_return_responsibility(monkeypatch, delta, expired):
    from service_app import assessed
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(minutes=15, microseconds=delta)
    monkeypatch.setattr(assessed, 'datetime', Clock)
    result = routes.repair_projection(row())
    assert result['state'] == 'issued'
    assert result['recovery'] is None
    assert result.get('return_coordination') == ('unavailable' if expired else None)


@pytest.mark.asyncio
@pytest.mark.parametrize('declined', [False, True])
async def test_single_read_uses_recovery_projection(monkeypatch, declined):
    import httpx
    from fastapi import FastAPI
    r = row()
    r['organization_id'] = UUID(FIXTURE['expected']['organization_id'])
    record = {'operator_id': 'retained', 'next_action': 'arrange_controlled_unrepaired_return'}
    decision = None
    if declined:
        r['state'] = 'declined_return_held'
        decision = {'decision': r['state'], 'actor_id': BUYER, 'decided_at': NOW,
                    'selected_line_ids': [], 'amounts': {}, 'terms_digest': 'a' * 64,
                    'accepted_fee_lines': {}, 'repair_recovery': json.dumps(record)}
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value=decision))
    @asynccontextmanager
    async def acquire():
        yield tx
    app = FastAPI()
    app.state.pool = SimpleNamespace(acquire=acquire)
    app.include_router(routes.router)
    p = SimpleNamespace(actor=SimpleNamespace(subject_id=BUYER, organization_id=None), roles=['buyer'])
    async def principal():
        return p
    app.dependency_overrides[routes.peers.principal] = principal
    monkeypatch.setattr(routes, 'load', AsyncMock(return_value=r))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/v1/repair-quotes/' + str(QUOTE))
    assert response.status_code == 200
    result = response.json()
    assert result['state'] == ('declined_return_held' if declined else 'issued')
    assert result['recovery'] == (record if declined else None)
    assert result.get('return_coordination') == (None if declined else 'unavailable')
    routes.load.assert_awaited_once_with(tx, QUOTE, 'repair')
    tx.fetchrow.assert_awaited_once_with('SELECT * FROM l14_quote_decisions WHERE quote_id=$1', QUOTE)
    p.actor.subject_id = UUID('00000000-0000-4000-8000-000000000099')
    tx.fetchrow.reset_mock()
    with pytest.raises(AccessDenied):
        await routes.read(QUOTE, SimpleNamespace(app=app), p)
    tx.fetchrow.assert_not_awaited()
