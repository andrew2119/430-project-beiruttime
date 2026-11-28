"""Pure contract, command, projection and HTTP boundary checks."""
import asyncio
import importlib.util
import json
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
import pytest
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / 'services/service-operations/modules/progress'
package = types.ModuleType('progress')
package.__path__ = [str(MODULE)]
sys.modules['progress'] = package
from progress.contracts import Access, Source, Command  # noqa: E402
from progress.model import Denied, authorize, project  # noqa: E402
from progress.service import execute, read  # noqa: E402
from progress.routes import router  # noqa: E402

spec = importlib.util.spec_from_file_location('progress_fixtures', ROOT / 'packages/contracts-service/progress/fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def source(**changes):
    return Source.model_validate({**fixtures.source(), **changes})


def command(**changes):
    return Command.model_validate({**fixtures.command(), **changes})


def access(actor=6, organization=3, **changes):
    return Access(actor_id=UUID(int=actor), organization_id=UUID(int=organization) if organization else None,
                  can_read=True, can_write=changes.get('can_write', True))


class Repository:
    """Local durable fixture for the transaction repository contract."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)')
        self.events = []

    async def lock(self, *_):
        pass

    async def job(self, subject):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (str(subject),)).fetchone()
        value = json.loads(row[0]) if row else [0, {}]
        return value[0], value[1]

    async def receipt(self, operation):
        row = self.db.execute('SELECT value FROM state WHERE key=?', ('op:' + str(operation),)).fetchone()
        if not row:
            return None
        value = json.loads(row[0])
        for key in ('actor_id', 'organization_id', 'subject_id'):
            value[key] = UUID(value[key])
        return value

    async def save(self, cmd, actor, report, reports, result, digest):
        receipt = dict(actor_id=str(actor.actor_id), organization_id=str(actor.organization_id),
                       subject_id=str(cmd.subject_id), request_hash=digest, result=result)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',
                            (str(cmd.subject_id), json.dumps([result['revision'], reports])))
            self.db.execute('INSERT INTO state VALUES(?,?)', ('op:' + str(cmd.operation_id), json.dumps(receipt)))
        self.events.append({'operation_id': str(cmd.operation_id), 'revision': result['revision']})


@pytest.fixture
def store(tmp_path):
    return Repository(tmp_path / 'progress.db')


async def provider(*_):
    return source()


def run(awaitable):
    return asyncio.run(awaitable)


def test_incomplete_required_line_forbids_ready(store):
    run(execute(store, provider, access(), command(state='completed'), lambda: NOW))
    rev, reports = run(store.job(UUID(int=1)))
    facts = source(quality_result='passed', quality_independent=True, quality_work_revision=rev, quality_scope_revision=1)
    result = project(facts, reports, rev, NOW)
    assert result['state'] == 'progress'
    assert [row['state'] for row in result['items']] == ['completed', 'not_started']
    assert result['release_authorized'] is False and result['execution_authorized'] is False


def test_current_quality_and_all_required_work(store):
    run(execute(store, provider, access(), command(state='completed'), lambda: NOW))
    run(execute(store, provider, access(), command(state='completed', expected_revision=1,
        operation_id=UUID(int=11), line_id=UUID(int=9)), lambda: NOW))
    rev, reports = run(store.job(UUID(int=1)))
    facts = source(quality_result='passed', quality_independent=True, quality_work_revision=2, quality_scope_revision=1)
    assert project(facts, reports, rev, NOW)['state'] == 'ready'
    for changes in ({'quality_work_revision': 1}, {'quality_independent': False}, {'quality_scope_revision': 2},
                    {'incident_open': True}, {'custody_current': False}, {'payment_held': False}):
        assert project(facts.model_copy(update=changes), reports, rev, NOW)['state'] != 'ready'


def test_material_change_pauses_and_new_scope_does_not_reuse_completion(store):
    run(execute(store, provider, access(), command(state='completed'), lambda: NOW))
    revision, reports = run(store.job(UUID(int=1)))
    facts = source(material_line_ids=[UUID(int=8)])
    assert project(facts, reports, revision, NOW)['items'][0]['state'] == 'paused'
    async def changed(*_):
        return facts
    with pytest.raises(Denied, match='material_change'):
        run(execute(store, changed, access(), command(expected_revision=1, operation_id=UUID(int=11)), lambda: NOW))
    assert project(source(scope_revision=2), reports, revision, NOW)['items'][0]['report'] is None


def test_restart_duplicate_and_conflicting_retry(store):
    cmd = command()
    result = run(execute(store, provider, access(), cmd, lambda: NOW))
    restarted = Repository(store.db.execute('PRAGMA database_list').fetchone()[2])
    assert run(execute(restarted, provider, access(), cmd, lambda: NOW)) == result
    assert run(restarted.job(cmd.subject_id))[0] == 1
    assert len(store.events) == 1 and not restarted.events
    with pytest.raises(Denied, match='operation_conflict'):
        run(execute(restarted, provider, access(), command(step_en='Different report'), lambda: NOW))


@pytest.mark.parametrize('actor,organization', [(5, 3), (6, 4), (99, None), (5, None)])
def test_denied_write_scope(store, actor, organization):
    with pytest.raises(Denied, match='denied'):
        run(execute(store, provider, access(actor, organization), command(), lambda: NOW))
    assert run(store.job(UUID(int=1)))[0] == 0


def test_buyer_read_and_revocation_even_after_acknowledgement(store):
    run(execute(store, provider, access(), command(), lambda: NOW))
    assert run(read(store, provider, access(5, None), UUID(int=1), 0, lambda: NOW))['total'] == 2
    async def revoked(*_):
        return source(assigned_actor_ids=[UUID(int=7)])
    with pytest.raises(Denied, match='denied'):
        run(execute(store, revoked, access(), command(), lambda: NOW))
    with pytest.raises(Denied, match='denied'):
        run(read(store, provider, access(99, None), UUID(int=1), 0, lambda: NOW))


@pytest.mark.parametrize('change', [{'expected_revision': 1}, {'source_revision': 2}, {'scope_revision': 2},
    {'quote_revision': 2}, {'policy_revision': 2}, {'watch_id': UUID(int=99)}, {'organization_id': UUID(int=99)}])
def test_stale_bindings(store, change):
    with pytest.raises(Denied, match='stale'):
        run(execute(store, provider, access(), command(**change), lambda: NOW))


@pytest.mark.parametrize('field', ['incident_open', 'commitment_current', 'custody_current', 'payment_held', 'scope_accepted'])
def test_current_prerequisites_hold_work(store, field):
    async def held(*_):
        return source(**{field: field == 'incident_open'})
    with pytest.raises(Denied, match='work_held'):
        run(execute(store, held, access(), command(), lambda: NOW))


@pytest.mark.parametrize('delta,allowed', [(-1, True), (0, False), (1, False)])
def test_authority_expiry_boundary(delta, allowed):
    facts = source(authority_until=NOW)
    if allowed:
        authorize(access(), facts, NOW + timedelta(microseconds=delta))
    else:
        with pytest.raises(Denied, match='unavailable'):
            authorize(access(), facts, NOW + timedelta(microseconds=delta))


@pytest.mark.parametrize('delta,overdue', [(-1, False), (0, True), (1, True)])
def test_wait_boundary_is_manual_not_automatic(store, delta, overdue):
    run(execute(store, provider, access(), command(state='waiting_parts'), lambda: NOW))
    revision, reports = run(store.job(UUID(int=1)))
    at = NOW + timedelta(minutes=30, microseconds=delta)
    row = project(source(), reports, revision, at)['items'][0]
    assert row['overdue'] is overdue
    assert row['state'] == 'waiting_parts' and row['report']['follow_up'] == 'review'


def test_timeout_invalid_provider_and_no_guessed_success(store):
    async def timeout(*_):
        raise TimeoutError()
    async def invalid(*_):
        return {'state': 'ready'}
    for upstream in (timeout, invalid):
        with pytest.raises(Denied, match='unavailable'):
            run(execute(store, upstream, access(), command(), lambda: NOW))
    assert run(store.job(UUID(int=1)))[0] == 0


def test_thousand_lines_server_pagination_and_mixed_text():
    line = fixtures.source()['accepted_lines'][0]
    lines = [{**line, 'line_id': UUID(int=100 + i), 'title_en': 'صيانة Repair ⌚ ' * 15} for i in range(1000)]
    facts = source(accepted_lines=lines)
    collected = []
    for offset in range(0, 1000, 50):
        page = project(facts, {}, 0, NOW, offset)
        assert page['total'] == 1000
        collected += page['items']
    assert len({row['line_id'] for row in collected}) == 1000
    assert page['next_offset'] is None
    for offset in (-1, 1, 1001):
        with pytest.raises(Denied):
            project(facts, {}, 0, NOW, offset)


@pytest.mark.parametrize('change', [{'expected_revision': True}, {'estimate_start': '2026-11-17T12:00:00Z'},
    {'next_review_at': '2026-11-17T12:30:00+02:00'}, {'step_ar': ' '}, {'evidence_refs': ['private']}])
def test_contract_rejects_invalid_and_private_fields(change):
    with pytest.raises(ValueError):
        command(**change)


def http_app(modules_path):
    app = create_app(Settings(database_url="postgresql://unused/unused", modules_path=modules_path))
    app.include_router(router)
    return app


def test_route_missing_provider_and_body_bounds(tmp_path):
    async def check():
        app = http_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/v1/progress/' + fixtures.identifier(1))).status_code == 503
            assert (await client.post('/v1/progress/' + fixtures.identifier(1), content=b'x' * 32769)).status_code == 413
            assert (await client.post('/v1/progress/' + fixtures.identifier(1), json={})).status_code == 422
    run(check())


@pytest.mark.parametrize('changes', [dict(organization_id=UUID(int=99)), dict(watch_id=UUID(int=99)),
    dict(quote_id=UUID(int=99)), dict(quote_revision=2), dict(policy_revision=2)])
def test_changed_binding_never_exposes_previous_report(store, changes):
    run(execute(store, provider, access(), command(state='completed'), lambda: NOW))
    revision, reports = run(store.job(UUID(int=1)))
    row = project(source(**changes), reports, revision, NOW)['items'][0]
    assert row['report'] is None and row['state'] == 'not_started'


def test_empty_scope_cannot_be_ready_and_held_followup_is_current():
    facts = source(accepted_lines=[], custody_current=False, quality_result='passed',
                   quality_independent=True, quality_scope_revision=1)
    result = project(facts, {}, 0, NOW)
    assert result['items'] == [] and result['total'] == 0 and result['state'] == 'held'
    assert result['next_actor'] == str(facts.responsible_actor_id)
    assert result['next_action_ar'] and result['next_action_en'] and result['next_review_at']
    assert project(source(accepted_lines=[], quality_result='passed', quality_independent=True,
                          quality_scope_revision=1), {}, 0, NOW)['state'] != 'ready'


def test_production_store_outbox_is_reference_only():
    from progress.store import Store
    class Transaction:
        def __init__(self):
            self.calls = []
        async def execute(self, sql, *args):
            self.calls.append((sql, args))
    tx = Transaction()
    cmd = command(step_en='Private customer report')
    result = {'revision': 1}
    run(Store(tx).save(cmd, access(), cmd.model_dump(mode='json'), {}, result, 'digest'))
    assert len(tx.calls) == 4
    sql, args = tx.calls[-1]
    assert 'service_progress_outbox' in sql
    payload = json.loads(args[-1])
    assert set(payload) == {'subject_id', 'watch_id', 'organization_id', 'revision', 'operation_id'}
    assert 'Private customer report' not in args[-1]
    assert not any(key in payload for key in ('ready', 'authorized', 'payment', 'quality', 'release'))


def test_packaged_contract_import_without_repository_layout(tmp_path):
    import shutil
    import subprocess
    root = tmp_path / 'domain-contracts'
    leaf = root / 'bt_contracts/service/progress'
    leaf.mkdir(parents=True)
    shutil.copyfile(ROOT / 'packages/contracts-service/progress/v1.py', leaf / 'v1.py')
    module = tmp_path / 'app/modules/progress'
    module.mkdir(parents=True)
    shutil.copyfile(MODULE / 'contracts.py', module / 'contracts.py')
    check = subprocess.run([sys.executable, '-c',
        "import runpy; value=runpy.run_path('app/modules/progress/contracts.py'); assert value['Source'].__module__ == 'bt_contracts.service.progress.v1'"],
        cwd=tmp_path, env={'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr



def test_populated_thousand_lines_and_stale_quality():
    line = fixtures.source()['accepted_lines'][0]
    lines = [{**line, 'line_id': UUID(int=100 + i)} for i in range(1000)]
    facts = source(accepted_lines=lines, quality_result='passed', quality_independent=True,
                   quality_scope_revision=1, quality_work_revision=1)
    base = command(state='completed').model_dump(mode='json')
    reports = {str(line['line_id']): {**base, 'line_id': str(line['line_id'])} for line in lines}
    result = project(facts, reports, 1, NOW)
    assert result['state'] == 'ready' and result['quality'] == 'passed'
    stale = project(facts, reports, 2, NOW)
    assert stale['state'] != 'ready' and stale['quality'] == 'missing'


@pytest.mark.parametrize('endpoint', ['detail', 'report', 'operation'])
def test_pool_acquisition_deadline_returns_unavailable(tmp_path, endpoint):
    class SaturatedPool:
        def acquire(self, *, timeout=None):
            assert timeout is not None and 0 < timeout <= 1.2
            class Acquisition:
                async def __aenter__(self):
                    raise TimeoutError()
                async def __aexit__(self, *_):
                    pass
            return Acquisition()

    async def check():
        app = http_app(tmp_path)
        app.state.progress_access = lambda _: asyncio.sleep(0, result=access())
        app.state.progress_source = provider
        app.state.pool = SaturatedPool()
        url = '/v1/progress/' + fixtures.identifier(1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            if endpoint == 'report':
                response = await client.post(url, json=fixtures.command())
            else:
                if endpoint == 'operation':
                    url += '/operations/' + fixtures.identifier(10)
                response = await client.get(url)
            assert response.status_code == 503
            assert response.json()['error']['code'] == 'unavailable'
    run(check())


@pytest.mark.parametrize('code,status', [('stale', 409), ('operation_conflict', 409),
    ('denied', 403), ('operation_missing', 404), ('unavailable', 503)])
def test_domain_codes_survive_shared_error_boundary(tmp_path, monkeypatch, code, status):
    from contextlib import asynccontextmanager
    import progress.routes as routes

    class Pool:
        @asynccontextmanager
        async def acquire(self, *, timeout):
            class Connection:
                @asynccontextmanager
                async def transaction(self):
                    yield
            yield Connection()

    async def rejected(*_):
        raise Denied(code, status)

    async def check():
        app = http_app(tmp_path)
        app.state.progress_access = lambda _: asyncio.sleep(0, result=access())
        app.state.progress_source = provider
        app.state.pool = Pool()
        monkeypatch.setattr(routes, 'execute', rejected)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/v1/progress/' + fixtures.identifier(1), json=fixtures.command())
            assert response.status_code == status
            error = response.json()['error']
            assert error['code'] == code
            assert error['request_id'] == response.headers['X-Request-ID']
            assert 'Movement examined' not in response.text
    run(check())


@pytest.mark.parametrize('case,status,code', [
    ('oversized', 413, 'body_too_large'),
    ('timeout', 408, 'request_timeout'),
    ('invalid', 422, 'invalid_command'),
    ('subject', 409, 'subject_mismatch'),
])
def test_request_rejections_have_bilingual_recovery(tmp_path, monkeypatch, case, status, code):
    from starlette.requests import Request

    async def timed_out_stream(self):
        raise TimeoutError()
        yield b''

    async def check():
        app = http_app(tmp_path)
        payload = fixtures.command()
        if case == 'subject':
            payload['subject_id'] = fixtures.identifier(99)
        if case == 'timeout':
            monkeypatch.setattr(Request, 'stream', timed_out_stream)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            url = '/v1/progress/' + fixtures.identifier(1)
            if case == 'oversized':
                response = await client.post(url, content=b'x' * 32769)
            else:
                response = await client.post(url, json={} if case == 'invalid' else payload)
            assert response.status_code == status
            error = response.json()['error']
            assert error['code'] == code
            assert error['request_id'] == response.headers['X-Request-ID']
            english, arabic = error['message'].split(' / ')
            assert 'retry' in english.lower()
            assert 'operation reference' in english
            assert 'مرجع العملية نفسه' in arabic or 'بمرجع العملية نفسه' in arabic
            assert any('\u0600' <= character <= '\u06ff' for character in arabic)
            assert payload['step_en'] not in response.text
            assert payload['operation_id'] not in response.text
    run(check())


@pytest.mark.parametrize('endpoint', ['detail', 'report', 'operation'])
@pytest.mark.parametrize('dependency', ['access', 'source'])
def test_connection_failure_has_bilingual_stable_retry(tmp_path, endpoint, dependency):
    from contextlib import asynccontextmanager

    class Pool:
        @asynccontextmanager
        async def acquire(self, *, timeout):
            class Connection:
                @asynccontextmanager
                async def transaction(self):
                    yield
                async def execute(self, *_):
                    pass
            yield Connection()

    async def disconnected(*_):
        raise ConnectionError('Private dependency details')

    async def check():
        app = http_app(tmp_path)
        app.state.progress_access = disconnected if dependency == 'access' else lambda _: asyncio.sleep(0, result=access())
        app.state.progress_source = disconnected if dependency == 'source' else provider
        app.state.pool = Pool()
        url = '/v1/progress/' + fixtures.identifier(1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            if endpoint == 'report':
                response = await client.post(url, json=fixtures.command())
            else:
                if endpoint == 'operation':
                    url += '/operations/' + fixtures.identifier(10)
                response = await client.get(url)
            assert response.status_code == 503
            error = response.json()['error']
            assert error['code'] == 'unavailable'
            assert 'same operation reference' in error['message']
            assert 'مرجع العملية نفسه' in error['message']
            assert 'Private dependency details' not in response.text
    run(check())


@pytest.mark.parametrize('method,path', [
    ('GET', '/invalid-reference'),
    ('POST', '/invalid-reference'),
    ('GET', '/' + fixtures.identifier(1) + '?offset=invalid'),
    ('GET', '/invalid-reference/operations/' + fixtures.identifier(10)),
    ('GET', '/' + fixtures.identifier(1) + '/operations/invalid-reference'),
])
def test_route_parameters_have_bilingual_recovery(tmp_path, method, path):
    async def check():
        app = http_app(tmp_path)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.request(method, '/v1/progress' + path)
            assert response.status_code == 422
            error = response.json()['error']
            assert error['code'] == 'invalid_parameters'
            assert 'same operation reference' in error['message']
            assert 'مرجع العملية نفسه' in error['message']
            assert error['request_id'] == response.headers['X-Request-ID']
    run(check())


@pytest.mark.parametrize('failure', [
    'LockNotAvailableError', 'QueryCanceledError', 'PostgresConnectionError',
    'ConnectionDoesNotExistError', 'CannotConnectNowError', 'TooManyConnectionsError',
])
@pytest.mark.parametrize('stage', ['acquire', 'statement', 'commit'])
def test_database_availability_failure_preserves_retry_and_transaction(tmp_path, monkeypatch, failure, stage):
    from contextlib import asynccontextmanager
    import asyncpg
    import progress.routes as routes

    error = getattr(asyncpg, failure)('Private database details')
    exits = []
    commands = []

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, kind, value, traceback):
            exits.append(kind)
            if stage == 'commit':
                raise error

    class Pool:
        @asynccontextmanager
        async def acquire(self, *, timeout):
            if stage == 'acquire':
                raise error

            class Connection:
                def transaction(self):
                    return Transaction()

            yield Connection()

    async def execute_report(store, provider, actor, cmd):
        commands.append(cmd.operation_id)
        if stage == 'statement':
            raise error
        return {'state': 'acknowledged'}

    async def check():
        app = http_app(tmp_path)
        app.state.progress_access = lambda _: asyncio.sleep(0, result=access())
        app.state.progress_source = provider
        app.state.pool = Pool()
        monkeypatch.setattr(routes, 'execute', execute_report)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            for _ in range(2):
                response = await client.post('/v1/progress/' + fixtures.identifier(1), json=fixtures.command())
                assert response.status_code == 503
                public = response.json()['error']
                assert public['code'] == 'unavailable'
                assert 'same operation reference' in public['message']
                assert 'مرجع العملية نفسه' in public['message']
                assert public['request_id'] == response.headers['X-Request-ID']
                assert 'Private database details' not in response.text
                assert 'acknowledged' not in response.text
        if stage == 'acquire':
            assert not exits and not commands
        else:
            assert commands == [UUID(fixtures.identifier(10))] * 2
            assert exits == ([type(error)] * 2 if stage == 'statement' else [None] * 2)

    run(check())


@pytest.mark.parametrize('delta', [-1, 0, 1])
def test_write_lease_checked_after_save_rolls_back(store, delta):
    from contextlib import contextmanager

    time = [NOW]
    original_save = store.save

    async def save(*args):
        await original_save(*args)
        time[0] = source().authority_until + timedelta(microseconds=delta)

    @contextmanager
    def transaction():
        # The HTTP adapter owns this boundary; preserve its rollback semantics.
        snapshot = store.db.serialize()
        try:
            yield
        except Denied:
            store.db.deserialize(snapshot)
            raise

    store.save = save
    if delta < 0:
        with transaction():
            assert run(execute(store, provider, access(), command(), lambda: time[0]))['revision'] == 1
    else:
        with pytest.raises(Denied, match='unavailable'), transaction():
            run(execute(store, provider, access(), command(), lambda: time[0]))
        assert run(store.job(UUID(int=1)))[0] == 0
        assert run(store.receipt(UUID(int=10))) is None


@pytest.mark.parametrize('delta', [-1, 0, 1])
def test_duplicate_lease_checked_after_receipt_read(store, delta):
    result = run(execute(store, provider, access(), command(), lambda: NOW))
    time = [NOW]
    original_receipt = store.receipt

    async def receipt(operation_id):
        value = await original_receipt(operation_id)
        time[0] = source().authority_until + timedelta(microseconds=delta)
        return value

    store.receipt = receipt
    if delta < 0:
        assert run(execute(store, provider, access(), command(), lambda: time[0])) == result
    else:
        with pytest.raises(Denied, match='unavailable'):
            run(execute(store, provider, access(), command(), lambda: time[0]))
    assert run(store.job(UUID(int=1)))[0] == 1


@pytest.mark.parametrize('delta', [-1, 0, 1])
def test_operation_lookup_lease_checked_after_receipt_read(tmp_path, monkeypatch, delta):
    from contextlib import asynccontextmanager
    import progress.routes as routes

    time = [NOW]
    exits = []

    class Clock:
        @staticmethod
        def now(_):
            return time[0]

    class Pool:
        @asynccontextmanager
        async def acquire(self, *, timeout):
            class Connection:
                @asynccontextmanager
                async def transaction(self):
                    try:
                        yield
                    except Denied:
                        exits.append('rollback')
                        raise
                    else:
                        exits.append('commit')
            yield Connection()

    async def receipt(self, operation_id):
        assert operation_id == UUID(int=10)
        time[0] = source().authority_until + timedelta(microseconds=delta)
        return dict(actor_id=UUID(int=6), organization_id=UUID(int=3), subject_id=UUID(int=1),
                    result={'state': 'acknowledged'})

    async def check():
        app = http_app(tmp_path)
        app.state.progress_access = lambda _: asyncio.sleep(0, result=access())
        app.state.progress_source = provider
        app.state.pool = Pool()
        monkeypatch.setattr(routes, 'datetime', Clock)
        monkeypatch.setattr(routes.Store, 'receipt', receipt)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/v1/progress/' + fixtures.identifier(1) + '/operations/' + fixtures.identifier(10))
            assert response.status_code == (200 if delta < 0 else 503)
            if delta >= 0:
                assert response.json()['error']['code'] == 'unavailable'
                assert 'acknowledged' not in response.text
        assert exits == (['commit'] if delta < 0 else ['rollback'])

    run(check())
