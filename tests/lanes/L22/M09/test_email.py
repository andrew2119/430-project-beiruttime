import asyncio
import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport

ROOT = Path(__file__).resolve().parents[4]
CONTRACT = ROOT / 'packages/contracts-comms/transaction-email'
MODULE = ROOT / 'services/communications/modules/transaction-email'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load('email_contract', CONTRACT / 'models.py')
package = types.ModuleType('email_module')
package.__path__ = [str(MODULE)]
sys.modules['email_module'] = package
service = load('email_module.service', MODULE / 'service.py')
routes = load('email_module.routes', MODULE / 'routes.py')
templates = load('email_module.templates', MODULE / 'templates.py')
FIXTURE = json.loads((CONTRACT / 'fixtures.v1.json').read_text())


def run(action):
    return asyncio.run(action)


@pytest.fixture
def setup(tmp_path):
    command = contract.Command.model_validate(FIXTURE['command'])
    current = {'value': contract.Authority.model_validate(FIXTURE['authority']), 'calls': 0}
    now = {'value': datetime.fromisoformat(FIXTURE['now'].replace('Z', '+00:00'))}

    async def provider(*_):
        current['calls'] += 1
        if isinstance(current['value'], Exception):
            raise current['value']
        return current['value']

    async def scope(actor, organization):
        value = current['value']
        if isinstance(value, Exception):
            raise value
        return contract.ReadScope(actor_id=value.actor_id, organization_id=value.organization_id,
            permitted=value.permitted, subject_ids={value.subject_id})
    async def admit(command, actor, organization, commit):
        return commit(await provider(command, actor, organization))
    provider.admit = admit
    provider.scope = scope
    box = service.Outbox(tmp_path / 'email.sqlite', provider, lambda: now['value'])
    return box, command, current, now


def capture(box, command):
    return run(box.capture(command, command.actor_id, command.organization_id))


def lookup(box, command):
    return run(box.lookup(command.operation_id, command.actor_id, command.organization_id, contract.Command))


def attempt(box, command, outcome='recorded'):
    return run(box.attempt(command.operation_id, command.actor_id, command.organization_id, contract.Command, outcome))


@pytest.mark.parametrize('kind', ['confirmation', 'quote', 'ready', 'refund', 'receipt-link'])
@pytest.mark.parametrize('locale', ['en', 'ar'])
def test_categories_and_languages(setup, kind, locale):
    box, command, current, _ = setup
    command = command.model_copy(update={'kind': kind, 'locale': locale})
    current['value'] = current['value'].model_copy(update={'kind': kind})
    result = capture(box, command)
    assert result['state'] == 'captured'
    result = attempt(box, command)
    assert result['state'] == 'recorded' and result['synthetic']
    contract.Result.model_validate(result)
    rendered = templates.render(result)
    assert rendered['subject'] and rendered['body'] and rendered['synthetic']
    assert rendered['direction'] == ('rtl' if locale == 'ar' else 'ltr')
    assert rendered['link'] == f'/{locale}/notification-email?operation_id={command.operation_id}'
    assert 'watch_id' not in rendered and 'quote_id' not in rendered


@pytest.mark.parametrize('case', FIXTURE['cases'][1:4])
def test_contract_negative_fixtures(setup, case):
    box, command, current, _ = setup
    current['value'] = current['value'].model_copy(update=case['override'])
    with pytest.raises(service.Rejected) as rejected:
        capture(box, command)
    assert rejected.value.code == case['code']
    with box.connection() as db:
        assert db.execute('SELECT count(*) FROM l22_email').fetchone()[0] == 0


def test_scope_and_revocation_on_every_operation(setup):
    box, command, current, _ = setup
    capture(box, command)
    for actor, organization in [(uuid4(), None), (command.actor_id, uuid4())]:
        with pytest.raises(service.Rejected):
            run(box.lookup(command.operation_id, actor, organization, contract.Command))
        with pytest.raises(service.Rejected):
            run(box.capture(command, actor, organization))
    current['value'] = current['value'].model_copy(update={'permitted': False})
    for action in [lambda: capture(box, command), lambda: lookup(box, command), lambda: attempt(box, command),
                   lambda: run(box.listing(command.actor_id, None, contract.Command)),
                   lambda: run(box.destination(command.operation_id, command.actor_id, None, contract.Command))]:
        with pytest.raises(service.Rejected, match='denied'):
            action()


@pytest.mark.parametrize('field,value', [('revision', 5), ('quote_id', uuid4()), ('policy_revision', 2), ('kind', 'refund')])
def test_stale_bindings(setup, field, value):
    box, command, current, _ = setup
    capture(box, command)
    current['value'] = current['value'].model_copy(update={field: value})
    with pytest.raises(service.Rejected, match='stale_revision'):
        lookup(box, command)


@pytest.mark.parametrize('delta,allowed', [(-1, True), (0, False), (1, False)])
def test_exact_authority_expiry(setup, delta, allowed):
    box, command, current, now = setup
    now['value'] = current['value'].valid_until + timedelta(microseconds=delta)
    if allowed:
        assert capture(box, command)['state'] == 'captured'
    else:
        with pytest.raises(service.Rejected, match='stale_revision'):
            capture(box, command)


def test_duplicate_conflicts_and_restart(setup):
    box, command, _, _ = setup
    first = capture(box, command)
    assert capture(box, command) == first
    with pytest.raises(service.Rejected, match='operation_conflict'):
        capture(box, command.model_copy(update={'locale': 'ar'}))
    with pytest.raises(service.Rejected, match='operation_conflict'):
        capture(box, command.model_copy(update={'operation_id': uuid4()}))
    recorded = attempt(box, command)
    restarted = service.Outbox(box.path, box.provider, box.clock)
    assert lookup(restarted, command) == recorded
    assert attempt(restarted, command) == recorded
    assert capture(restarted, command) == recorded


def test_unknown_and_failed_never_resend(setup):
    box, command, _, now = setup
    capture(box, command)
    unknown = attempt(box, command, 'possibly_sent')
    assert unknown['next_actor'] == FIXTURE['authority']['support_actor_id']
    assert datetime.fromisoformat(unknown['next_review_at']) == now['value'] + timedelta(hours=24)
    restarted = service.Outbox(box.path, box.provider, box.clock)
    assert attempt(restarted, command) == unknown
    assert unknown['attempt_id'] is not None and unknown['state'] == 'possibly_sent'


def test_failed_retains_identity(setup):
    box, command, _, _ = setup
    capture(box, command)
    failed = attempt(box, command, 'failed')
    assert failed['state'] == 'failed' and failed['next_review_at']
    assert attempt(box, command) == failed


def test_provider_failure_is_closed_and_durable(setup):
    box, command, current, _ = setup
    saved = capture(box, command)
    authority = current['value']
    current['value'] = TimeoutError()
    with pytest.raises(service.Rejected, match='unavailable'):
        lookup(box, command)
    current['value'] = authority
    assert lookup(service.Outbox(box.path, box.provider, box.clock), command) == saved


def test_provider_deadline(setup):
    box, command, _, _ = setup
    async def slow(*_):
        await asyncio.sleep(3)
    box.provider = slow
    with pytest.raises(service.Rejected, match='unavailable'):
        capture(box, command)


def test_changed_recipient_after_capture(setup):
    box, command, current, _ = setup
    capture(box, command)
    current['value'] = current['value'].model_copy(update={'recipient_revision': 3, 'verified_revision': 3})
    with pytest.raises(service.Rejected, match='recipient_unverified'):
        attempt(box, command)
    with box.connection() as db:
        assert db.execute('SELECT attempt FROM l22_email').fetchone()[0] is None


def test_current_destination_and_no_private_payload(setup):
    box, command, _, _ = setup
    record = capture(box, command)
    destination = run(box.destination(command.operation_id, command.actor_id, None, contract.Command))
    assert destination == {'url': '/checkout/' + str(command.subject_id)}
    assert all(word not in json.dumps(record) for word in ['address', 'evidence', 'token', 'password', 'maximum'])


def test_pagination_1000_and_bounds(setup):
    box, command, _, _ = setup
    capture(box, command)
    with box.connection() as db:
        original = tuple(db.execute('SELECT * FROM l22_email').fetchone())
        for _ in range(999):
            operation, event = str(uuid4()), str(uuid4())
            data = json.loads(original[5]); data.update(operation_id=operation)
            values = (operation, original[1], original[2], event, original[4], json.dumps(data), *original[6:])
            db.execute('INSERT INTO l22_email VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
    ids = set()
    for offset in range(0, 1000, 50):
        page = run(box.listing(command.actor_id, None, contract.Command, offset, 50))
        assert page['total'] == 1000 and len(page['items']) == 50
        ids.update(item['operation_id'] for item in page['items'])
    assert len(ids) == 1000
    for offset, limit in [(-1,20), (0,51), (100001,20), (0,0), (False,20)]:
        with pytest.raises(service.Rejected):
            run(box.listing(command.actor_id, None, contract.Command, offset, limit))


def test_schema_strictness():
    for field, value in [('expected_revision', True), ('recipient_revision', 1.5), ('locale', 'xx'), ('quote_revision', 1), ('private_file', 'hidden')]:
        with pytest.raises(ValueError):
            contract.Command.model_validate(FIXTURE['command'] | {field: value})


def test_route_auth_bounds_and_lookup(setup):
    box, command, _, _ = setup
    identity = types.SimpleNamespace(actor_id=command.actor_id, organization_id=None)
    async def principal():
        return identity
    async def producer():
        raise HTTPException(403)
    app = FastAPI()
    app.include_router(routes.create_router(box, contract.Command, principal, producer))
    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.post('/internal/v1/transaction-email', json=FIXTURE['command'])).status_code == 403
            app.dependency_overrides[producer] = principal
            result = await client.post('/internal/v1/transaction-email', json=FIXTURE['command'])
            assert result.status_code == 200
            assert result.headers['cache-control'] == 'no-store'
            path = '/v1/transaction-email/operations/' + str(command.operation_id)
            assert (await client.get(path)).json()['operation_id'] == str(command.operation_id)
            assert (await client.post(path+'/destination')).json()['url'].startswith('/checkout/')
            assert (await client.get('/v1/transaction-email?limit=51')).status_code == 422
            assert (await client.post('/internal/v1/transaction-email', content='x'*4097)).status_code == 413
            assert (await client.post('/internal/v1/transaction-email', json=FIXTURE['command']|{'evidence':'private'})).status_code == 422
    run(exercise())


def test_crash_after_uncertainty_commit_never_repeats(setup):
    from contextlib import contextmanager
    box, command, _, _ = setup
    capture(box, command)
    original = box.connection
    calls = {'count': 0}

    @contextmanager
    def interrupted():
        calls['count'] += 1
        if calls['count'] == 3:
            raise RuntimeError('interrupted')
        with original() as db:
            yield db

    box.connection = interrupted
    with pytest.raises(service.Rejected, match='unavailable'):
        attempt(box, command)
    restarted = service.Outbox(box.path, box.provider, box.clock)
    recovered = attempt(restarted, command)
    assert recovered['state'] == 'possibly_sent'
    assert recovered['attempt_id'] is not None
    assert recovered['next_actor'] == FIXTURE['authority']['support_actor_id']


def test_concurrent_duplicates_have_one_attempt(setup):
    box, command, _, _ = setup
    async def exercise():
        results = await asyncio.gather(*(box.capture(command, command.actor_id, None) for _ in range(12)))
        assert all(result == results[0] for result in results)
        attempts = await asyncio.gather(*(box.attempt(command.operation_id, command.actor_id, None, contract.Command) for _ in range(12)))
        assert all(result == attempts[0] for result in attempts)
    run(exercise())
    with box.connection() as db:
        assert db.execute('SELECT count(*) FROM l22_email').fetchone()[0] == 1
        content = json.loads(db.execute('SELECT content FROM l22_email').fetchone()[0])
        assert content['verified_revision'] == command.recipient_revision
        assert content['message']['body'] == templates.COPY[command.locale]['body']


@pytest.mark.parametrize('delta,allowed', [(-1, True), (0, True), (1, False)])
def test_actual_event_time_boundary(setup, delta, allowed):
    box, command, current, now = setup
    current['value'] = current['value'].model_copy(update={'occurred_at':now['value']+timedelta(microseconds=delta)})
    if allowed:
        capture(box, command)
    else:
        with pytest.raises(service.Rejected, match='stale_revision'):
            capture(box, command)


def test_empty_page_rechecks_scope_and_never_discloses_revoked_total(setup):
    box, command, current, _ = setup
    capture(box, command)
    current['value'] = current['value'].model_copy(update={'permitted':False})
    with pytest.raises(service.Rejected, match='denied'):
        run(box.listing(command.actor_id, None, contract.Command, 100, 20))
    async def reduced_scope(*_):
        return contract.ReadScope(actor_id=command.actor_id, organization_id=None, permitted=True, subject_ids=set())
    box.provider.scope = reduced_scope
    page = run(box.listing(command.actor_id, None, contract.Command))
    assert page['items'] == [] and page['total'] == 0


def test_missing_scope_provider_fails_closed_even_for_empty_page(setup):
    box, command, _, _ = setup
    del box.provider.scope
    with pytest.raises(service.Rejected, match='unavailable'):
        run(box.listing(command.actor_id, None, contract.Command, 100, 20))


@pytest.mark.parametrize('action', ['capture', 'attempt'])
def test_snapshot_expiring_during_storage_admission_is_rejected(setup, action):
    box, command, current, now = setup
    if action == 'attempt':
        capture(box, command)
    instants = iter([now['value'], current['value'].valid_until])
    box.clock = lambda: next(instants)
    with pytest.raises(service.Rejected, match='stale_revision'):
        capture(box, command) if action == 'capture' else attempt(box, command)
    with box.connection() as db:
        rows = db.execute('SELECT state,attempt FROM l22_email').fetchall()
        assert (not rows) if action == 'capture' else (rows[0]['state'] == 'captured' and rows[0]['attempt'] is None)


@pytest.mark.parametrize('action', ['capture', 'attempt'])
@pytest.mark.parametrize('change,code', [({'permitted': False}, 'denied'),
    ({'recipient_revision': 3, 'verified_revision': 3}, 'recipient_unverified')])
def test_admission_rechecks_after_snapshot(setup, action, change, code):
    box, command, current, _ = setup
    if action == 'attempt':
        capture(box, command)
    async def admit(command, actor, organization, commit):
        current['value'] = current['value'].model_copy(update=change)
        return commit(current['value'])
    box.provider.admit = admit
    with pytest.raises(service.Rejected, match=code):
        capture(box, command) if action == 'capture' else attempt(box, command)
    with box.connection() as db:
        rows = db.execute('SELECT state,attempt FROM l22_email').fetchall()
        assert not rows if action == 'capture' else rows[0]['state'] == 'captured' and rows[0]['attempt'] is None


def test_snapshot_only_provider_cannot_admit(setup):
    box, command, _, _ = setup
    del box.provider.admit
    with pytest.raises(service.Rejected, match='unavailable'):
        capture(box, command)
