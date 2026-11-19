import asyncio
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('l18_inspection', ROOT / 'services/trust/modules/private-inspection/service.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def uid(n):
    return str(UUID(int=n))


NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def source():
    return dict(subject_id=uid(1), watch_id=uid(2), watch_revision=1, actor_id=uid(3), organization_id=uid(4),
                assignment_revision=1, quote_id=uid(5), quote_revision=1, policy_revision=1, source_revision=1,
                seller_id=uid(6), buyer_id=uid(7), expert_id=uid(3), expert_independent=True, authorized=True,
                seller_kind='private', commitment_current=True, payment_state='paid_held',
                payment_operation_id=uid(8), payment_revision=1, custody_receipt_id=uid(9),
                custody_watch_revision=1, custody_to_actor=uid(3), authorized_recipient=uid(3),
                received_at=NOW.isoformat(), custody_current=True, incident_open=False, proof_revision=1,
                checklist_revision=1, evidence_refs=[uid(10)], currency='USD', price_minor=500000,
                buyer_fee_minor=15000, seller_commission_minor=25000, return_trip_minor=3000,
                return_line_accepted=True, saved_simulated_method_id=uid(11), checked_at=NOW.isoformat(),
                valid_until=(NOW + timedelta(seconds=30)).isoformat())


def command(result='passed'):
    s = source()
    body = {key: s[key] for key in module.contract.Binding.model_fields}
    body.update(schema_version='private-inspection.v1', operation_id=uid(12), expected_revision=0,
                custody_receipt_id=uid(9), checklist_revision=1,
                checklist=[{'item': key, 'verdict': result} for key in ('identity', 'movement', 'case', 'provenance')],
                evidence_refs=[uid(10)], result=result, reason='Actual watch inspected / تم فحص الساعة الفعلية')
    return body


class Provider:
    def __init__(self):
        self.facts = source()
        self.collection_facts = None
        self.error = None

    async def current(self, *_):
        if self.error:
            raise self.error
        return self.facts

    async def collection(self, *_):
        return self.collection_facts


@pytest.fixture
def setup(tmp_path):
    provider = Provider()
    service = module.Inspection(tmp_path / 'inspection.db', provider, lambda: NOW)
    yield service, provider
    service.close()


def run(call):
    return asyncio.run(call)


def submit(service, body=None):
    return run(service.submit(uid(3), uid(4), body or command()))


def current(service):
    return run(service.current(uid(3), uid(4), uid(1)))


@pytest.mark.parametrize('field,value,code', [
    ('payment_state', 'unpaid', 'prerequisites_required'),
    ('payment_state', 'pending', 'prerequisites_required'),
    ('custody_current', False, 'prerequisites_required'),
    ('commitment_current', False, 'prerequisites_required'),
    ('incident_open', True, 'prerequisites_required'),
    ('custody_watch_revision', 2, 'prerequisites_required'),
    ('custody_to_actor', uid(7), 'prerequisites_required'),
    ('authorized_recipient', uid(6), 'prerequisites_required'),
    ('expert_independent', False, 'independence_required'),
    ('seller_id', uid(3), 'independence_required'),
    ('buyer_id', uid(3), 'independence_required'),
    ('authorized', False, 'denied'),
    ('organization_id', uid(90), 'denied'),
    ('watch_revision', 2, 'prerequisites_required'),
    ('seller_kind', 'dealer', 'business_assurance_route'),
    ('seller_kind', 'brand', 'business_assurance_route'),
    ('quote_revision', 2, 'stale_revision'),
    ('assignment_revision', 2, 'stale_revision'),
    ('source_revision', 2, 'stale_revision'),
    ('checklist_revision', 2, 'stale_revision'),
    ('seller_commission_minor', 0, 'retained_economics_required'),
    ('return_line_accepted', False, 'retained_economics_required'),
    ('price_minor', float('inf'), 'unavailable'),
    ('price_minor', True, 'unavailable'),
    ('received_at', (NOW + timedelta(seconds=1)).isoformat(), 'prerequisites_required'),
])
def test_denials(setup, field, value, code):
    service, provider = setup
    provider.facts[field] = value
    with pytest.raises(module.Refusal, match=code):
        submit(service)
    assert service.db.execute('SELECT count(*) FROM l18_results').fetchone()[0] == 0


def test_attributable_pass_and_private_outbox(setup):
    service, _ = setup
    receipt = submit(service)
    assert receipt['revision'] == 1 and receipt['actor_id'] == uid(3)
    assert current(service)['inspection_prerequisite_passed']
    assert 'evidence_refs' not in json.dumps(receipt)
    events = service.db.execute('SELECT body FROM l18_outbox').fetchall()
    assert len(events) == 1
    assert uid(10) not in events[0][0] and 'reason' not in events[0][0]
    assert service.saved(uid(1))['reason'] == command()['reason']


def test_restart_lost_response_duplicate_and_lookup(setup, tmp_path):
    service, provider = setup
    original = submit(service)
    second = module.Inspection(tmp_path / 'inspection.db', provider, lambda: NOW)
    try:
        assert submit(second) == original
        assert run(second.lookup(uid(3), uid(4), uid(1), uid(12))) == original
        assert second.db.execute('SELECT count(*) FROM l18_outbox').fetchone()[0] == 1
    finally:
        second.close()


def test_conflict_stale_and_revoked_retry(setup):
    service, provider = setup
    submit(service)
    altered = command()
    altered['reason'] = 'Different reason'
    with pytest.raises(module.Refusal, match='operation_conflict'):
        submit(service, altered)
    altered['operation_id'] = uid(13)
    with pytest.raises(module.Refusal, match='stale_revision'):
        submit(service, altered)
    provider.facts['authorized'] = False
    with pytest.raises(module.Refusal, match='denied'):
        submit(service)


@pytest.mark.parametrize('offset,allowed', [(-1, True), (0, False), (1, False)])
def test_exact_freshness_boundary(setup, offset, allowed):
    service, provider = setup
    provider.facts['valid_until'] = (NOW - timedelta(seconds=offset)).isoformat()
    if allowed:
        assert submit(service)['state'] == 'passed'
    else:
        with pytest.raises(module.Refusal, match='unavailable'):
            submit(service)


def test_checked_at_equality_and_naive_time(setup):
    service, provider = setup
    assert submit(service)['state'] == 'passed'
    provider.facts['checked_at'] = NOW.replace(tzinfo=None).isoformat()
    with pytest.raises(module.Refusal, match='unavailable'):
        current(service)


@pytest.mark.parametrize('error', [TimeoutError(), OSError()])
def test_dependency_failure(setup, error):
    service, provider = setup
    provider.error = error
    with pytest.raises(module.Refusal, match='unavailable'):
        submit(service)


@pytest.mark.parametrize('result', ['failed', 'inconclusive'])
def test_blocked_outcomes(setup, result):
    service, provider = setup
    submit(service, command(result))
    facts = current(service)
    assert facts['buyer_handover_blocked'] and facts['seller_payout_blocked'] and facts['return_blocked']
    assert facts['buyer_watch_price_refund_ready'] == (result == 'failed')
    assert facts['refundable_fee_minor'] == 0
    if result == 'failed':
        assert facts['charge_amount_minor'] == 28000
        assert facts['refundable_watch_price_minor'] == 500000
        assert datetime.fromisoformat(facts['next_review_at']) == NOW + timedelta(hours=24)
        kinds = service.db.execute('SELECT kind FROM l18_outbox').fetchall()
        assert len(kinds) == 3
        revised = command()
        revised.update(operation_id=uid(13), expected_revision=1)
        with pytest.raises(module.Refusal, match='operational_decision_required'):
            submit(service, revised)


@pytest.mark.parametrize('state,blocked', [('unknown', True), ('declined', True), ('pending', True), ('confirmed', False)])
def test_collection_only_controls_return(setup, state, blocked):
    service, provider = setup
    submit(service, command('failed'))
    facts = current(service)
    provider.collection_facts = dict(watch_id=uid(2), watch_revision=1, source_revision=1, result_revision=1,
                                    assignment_revision=1, custody_receipt_id=uid(9),
                                    operation_id=facts['charge_operation_id'], subject_id=uid(1), seller_id=uid(6),
                                    method_id=uid(11), currency='USD', amount_minor=28000, state=state,
                                    custody_instruction_id=uid(20), checked_at=NOW.isoformat(),
                                    valid_until=(NOW + timedelta(seconds=20)).isoformat())
    result = run(service.return_readiness(uid(3), uid(4), uid(1)))
    assert result['return_blocked'] == blocked
    assert result['buyer_watch_price_refund_ready'] and result['seller_payout_blocked']
    provider.collection_facts['amount_minor'] = 1
    with pytest.raises(module.Refusal, match='collection_binding_mismatch'):
        run(service.return_readiness(uid(3), uid(4), uid(1)))


def test_missing_collection_retains_refund_basis(setup):
    service, _ = setup
    submit(service, command('failed'))
    facts = run(service.return_readiness(uid(3), uid(4), uid(1)))
    assert facts['return_blocked'] and facts['buyer_watch_price_refund_ready']


def test_current_result_rechecks_source_and_cross_scope_lookup(setup):
    service, provider = setup
    submit(service)
    with pytest.raises(module.Refusal, match='denied'):
        run(service.lookup(uid(90), uid(4), uid(1), uid(12)))
    provider.facts['quote_revision'] = 2
    with pytest.raises(module.Refusal, match='stale_revision'):
        current(service)


@pytest.mark.parametrize('change', ['evidence', 'checklist', 'result', 'size', 'float', 'extra'])
def test_bounded_commands(setup, change):
    service, _ = setup
    body = command()
    if change == 'evidence':
        body['evidence_refs'] = [uid(99)]
    elif change == 'checklist':
        body['checklist'][0] = body['checklist'][1]
    elif change == 'result':
        body['result'] = 'failed'
    elif change == 'size':
        body['reason'] = 'x' * 17000
    elif change == 'float':
        body['expected_revision'] = 0.0
    else:
        body['buyer_received'] = True
    with pytest.raises(module.Refusal):
        submit(service, body)


def test_atomic_rollback(setup):
    service, _ = setup
    service.db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON l18_outbox BEGIN SELECT RAISE(ABORT,'closed'); END")
    with pytest.raises(Exception, match='closed'):
        submit(service)
    assert service.saved(uid(1)) is None
    assert service.db.execute('SELECT count(*) FROM l18_operations').fetchone()[0] == 0


def test_immutable_findings_and_complete_receipts(setup):
    service, _ = setup
    first = submit(service, command('inconclusive'))
    body = command()
    body.update(operation_id=uid(13), expected_revision=1, reason='Additional actual findings')
    submit(service, body)
    history = [json.loads(row[0]) for row in service.db.execute('SELECT body FROM l18_history ORDER BY revision')]
    assert len(history) == 2
    assert history[0]['reason'] == command()['reason']
    assert history[0]['state'] == 'inconclusive' and history[1]['state'] == 'passed'
    assert first['source_revision'] == first['quote_revision'] == first['watch_revision'] == 1
    assert first['custody_receipt_id'] == uid(9) and first['payment_operation_id'] == uid(8)


def test_naive_receipt_unavailable(setup):
    service, provider = setup
    provider.facts['received_at'] = NOW.replace(tzinfo=None).isoformat()
    with pytest.raises(module.Refusal, match='unavailable'):
        submit(service)


def test_collection_expiry_during_final_recheck(setup):
    service, provider = setup
    submit(service, command('failed'))
    facts = current(service)
    provider.collection_facts = dict(watch_id=uid(2), watch_revision=1, source_revision=1, result_revision=1,
                                    assignment_revision=1, custody_receipt_id=uid(9),
                                    operation_id=facts['charge_operation_id'], subject_id=uid(1), seller_id=uid(6),
                                    method_id=uid(11), currency='USD', amount_minor=28000, state='confirmed',
                                    custody_instruction_id=uid(20), checked_at=NOW.isoformat(),
                                    valid_until=(NOW + timedelta(seconds=1)).isoformat())
    old = provider.current
    calls = 0

    async def advancing(*args):
        nonlocal calls
        calls += 1
        if calls == 3:
            service.clock = lambda: NOW + timedelta(seconds=1)
        return await old(*args)

    provider.current = advancing
    assert run(service.return_readiness(uid(3), uid(4), uid(1)))['return_blocked']


def test_http_boundary_and_request_limits(setup):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    route_spec = importlib.util.spec_from_file_location('l18_routes', ROOT / 'services/trust/modules/private-inspection/routes.py')
    routes = importlib.util.module_from_spec(route_spec)
    route_spec.loader.exec_module(routes)
    service, provider = setup
    app = FastAPI()

    async def scope():
        return SimpleNamespace(actor_id=uid(3), organization_id=uid(4))

    app.include_router(routes.router_for(service, scope))

    async def requests():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://inspection.invalid') as client:
            assert (await client.get(f'/v1/private-inspections/{uid(1)}/workspace')).status_code == 200
            result = await client.post('/v1/private-inspections/results', json=command())
            assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
            lookup = await client.get(f'/v1/private-inspections/operations/{uid(12)}?subject_id={uid(1)}')
            assert lookup.json() == result.json()
            assert (await client.post('/v1/private-inspections/results', content='x' * 17000)).status_code == 413
            assert (await client.post('/v1/private-inspections/results', content='[]')).status_code == 422
            provider.facts['authorized'] = False
            denial = await client.get(f'/v1/private-inspections/{uid(1)}/current')
            assert denial.status_code == 403
            assert set(denial.json()['error']['message']) == {'en', 'ar'}

    run(requests())


def test_published_fixtures_are_schema_valid_and_deterministic(setup):
    service, provider = setup
    fixtures = json.loads((ROOT / 'packages/contracts-trust/private-inspection/fixtures.json').read_text())
    for name in ('success', 'denied', 'stale', 'lost_response'):
        case = fixtures[name]
        module.Source.model_validate(case['source'])
        module.Submit.model_validate(case['command'])
    case = fixtures['success']
    provider.facts = case['source']
    assert submit(service, case['command']) == case['receipt']
    assert submit(service, fixtures['lost_response']['retry_command']) == case['receipt']
    module.contract.Receipt.model_validate(case['receipt'])
    for name in ('denied', 'stale'):
        provider.facts = fixtures[name]['source']
        body = dict(fixtures[name]['command'], operation_id=uid(100))
        with pytest.raises(module.Refusal, match=fixtures[name]['error']['code']):
            submit(service, body)


def test_workspace_does_not_project_pass_from_changed_payment(setup):
    service, provider = setup
    submit(service)
    provider.facts['payment_revision'] = 2
    workspace = run(service.workspace(uid(3), uid(4), uid(1)))
    assert workspace['current_state'] is None
    with pytest.raises(module.Refusal, match='stale_revision'):
        current(service)


def test_serialized_identical_retries(setup):
    service, _ = setup

    async def retries():
        return await asyncio.gather(*(service.submit(uid(3), uid(4), command()) for _ in range(3)))

    answers = run(retries())
    assert answers[0] == answers[1] == answers[2]
    assert service.db.execute('SELECT count(*) FROM l18_history').fetchone()[0] == 1


def test_current_financial_facts_have_versioned_schema(setup):
    service, _ = setup
    submit(service, command('failed'))
    facts = module.contract.CurrentResult.model_validate(current(service))
    assert facts.charge_amount_minor == 28000
    assert facts.refundable_watch_price_minor == 500000 and facts.refundable_fee_minor == 0


@pytest.mark.parametrize('failure', ['expired', 'revoked', 'changed', 'fresh'])
@pytest.mark.parametrize('error', [TimeoutError, OSError, ValueError])
def test_collection_failure_rechecks_authority(setup, failure, error):
    service, provider = setup
    submit(service, command('failed'))

    async def collection(_):
        if failure == 'expired':
            service.clock = lambda: NOW + timedelta(seconds=30)
        elif failure == 'revoked':
            provider.facts['authorized'] = False
        elif failure == 'changed':
            provider.facts['source_revision'] = 2
        raise error()

    provider.collection = collection
    if failure == 'fresh':
        facts = run(service.return_readiness(uid(3), uid(4), uid(1)))
        assert facts['return_blocked'] and facts['buyer_watch_price_refund_ready']
        assert facts['pending_reason'] == 'collection_unavailable'
    else:
        code = {'expired': 'unavailable', 'revoked': 'denied', 'changed': 'stale_revision'}[failure]
        with pytest.raises(module.Refusal, match=code):
            run(service.return_readiness(uid(3), uid(4), uid(1)))


@pytest.mark.parametrize('path', [
    '/not-a-reference/workspace',
    '/not-a-reference/current',
    '/not-a-reference/return-readiness',
    f'/operations/not-a-reference?subject_id={uid(1)}',
    f'/operations/{uid(12)}?subject_id=not-a-reference',
    f'/operations/{uid(12)}',
])
def test_invalid_route_references_have_private_bilingual_recovery(setup, path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    route_spec = importlib.util.spec_from_file_location(
        'l18_validation_routes', ROOT / 'services/trust/modules/private-inspection/routes.py')
    routes = importlib.util.module_from_spec(route_spec)
    route_spec.loader.exec_module(routes)
    service, provider = setup
    app = FastAPI()

    async def scope():
        return SimpleNamespace(actor_id=uid(3), organization_id=uid(4))

    async def unexpected_read(*_):
        pytest.fail('Invalid reference reached the current-source boundary')

    provider.current = unexpected_read
    app.include_router(routes.router_for(service, scope))

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://inspection.invalid') as client:
            response = await client.get('/v1/private-inspections' + path)
        assert response.status_code == 422
        assert response.headers['cache-control'] == 'no-store'
        assert response.json() == {'error': {
            'code': 'invalid_request', 'message': routes.COPY, 'request_id': ''}}
        assert all(response.json()['error']['message'][locale] for locale in ('en', 'ar'))

    run(request())
