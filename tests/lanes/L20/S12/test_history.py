import asyncio
import importlib.util
import sys
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load('history_contract', 'packages/contracts-service/history/v1.py')
model = load('history_reader', 'services/service-operations/modules/history/reader.py')
uid = lambda n: UUID(int=n)


def row():
    return dict(job_id=uid(4), watch_id=uid(3), organization_id=uid(5), kind='service',
        work_codes=['repair'], released_at='2026-11-01T00:00:00Z', source_revision=2,
        warranty=None, state='released_completed', actual_work=True, current_quality='passed',
        privacy_reviewed=True, former_owner_name='Restricted person', evidence_refs=['private'])


class Provider:
    def __init__(self):
        self.scope = model.Scope(True, 2)
        self.source = model.Source(2, True, 1, (row(),))
        self.receipts = {}
        self.fail = False

    async def lookup_publication(self, operation_id, actor_id):
        return None

    async def authorize(self, read):
        return self.scope

    async def remember(self, read):
        previous = self.receipts.setdefault(read.operation_id, read)
        return previous == read

    async def lookup(self, operation_id, actor_id):
        return self.receipts.get(operation_id)

    async def released(self, read):
        if self.fail:
            raise TimeoutError()
        return self.source


@pytest.fixture
def setup():
    provider = Provider()
    read = model.Read(uid(1), uid(2), uid(2), uid(3), None, 2)
    return provider, read


def run(provider, read):
    return asyncio.run(model.Reader(provider, contract).read(read))


@pytest.mark.parametrize('kind,work', [('service', 'repair'), ('modification', 'customization')])
def test_safe_released_work(setup, kind, work):
    provider, read = setup
    provider.source.rows[0]['kind'] = kind
    provider.source.rows[0]['work_codes'] = [work]
    result = run(provider, read)
    assert result.state == 'ready'
    encoded = result.model_dump_json()
    assert 'Restricted person' not in encoded and 'evidence' not in encoded
    assert result.items[0].job_id == uid(4)
    assert result.items[0].kind == kind and result.items[0].work_codes == (work,)


@pytest.mark.parametrize('state', ['pending', 'rework', 'handover_ready', 'unrepaired_return'])
def test_noncompletion_fails_closed(setup, state):
    provider, read = setup
    provider.source.rows[0]['state'] = state
    assert run(provider, read).state == 'unavailable'
    assert not run(provider, read).items


@pytest.mark.parametrize('field,value', [('actual_work', False), ('privacy_reviewed', False), ('current_quality', 'failed')])
def test_missing_fact(setup, field, value):
    provider, read = setup
    provider.source.rows[0][field] = value
    assert run(provider, read).state == 'unavailable'


def test_denied_stale_wrong_organization(setup):
    provider, read = setup
    provider.scope = model.Scope(False, 2)
    assert run(provider, read).state == 'denied'
    provider.scope = model.Scope(True, 3)
    assert run(provider, read).state == 'stale'
    provider.scope = model.Scope(True, 2)
    assert run(provider, replace(read, organization_id=uid(9))).state == 'denied'


def test_duplicate_timeout_restart_lookup(setup):
    provider, read = setup
    provider.fail = True
    assert run(provider, read).state == 'unavailable'
    provider.fail = False
    restarted = model.Reader(provider, contract)
    result = asyncio.run(restarted.lookup(read.operation_id, read.actor_id, read.subject_id, read.organization_id))
    assert result.state == 'ready'
    assert run(provider, read) == result
    assert run(provider, replace(read, watch_id=uid(9))).state == 'denied'
    assert asyncio.run(restarted.lookup(read.operation_id, uid(99), read.subject_id, read.organization_id)) is None


def test_pending_and_late_revision(setup):
    provider, read = setup
    provider.source = replace(provider.source, settled=False)
    assert run(provider, read).state == 'pending'
    provider.source = replace(provider.source, revision=3)
    assert run(provider, read).state == 'stale'


def test_revocation_during_read(setup):
    provider, read = setup
    async def released(_):
        provider.scope = model.Scope(False, 2)
        return provider.source
    provider.released = released
    assert run(provider, read).state == 'denied'


@pytest.mark.parametrize('offset', [-1, 0, 1])
def test_warranty_exact_utc_start(offset):
    start = datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)
    warranty = contract.Warranty(issuer_id=uid(5), scope_code='accepted_work', starts_at=start,
        terms_revision=1, terms_en='Synthetic terms', terms_ar='شروط تجريبية')
    assert warranty.starts_at == start
    with pytest.raises(ValueError):
        warranty.terms_revision = 2


@pytest.mark.parametrize('count', [0, 1, 1000])
def test_server_total_pagination(setup, count):
    provider, read = setup
    for page in range(max(1, (count+19)//20)):
        rows = tuple({**row(), 'job_id':uid(100+i)} for i in range(page*20, min(count, page*20+20)))
        provider.source = model.Source(2, True, count, rows)
        result = run(provider, replace(read, page=page, operation_id=uid(10000+page)))
        assert result.state == 'ready' and result.total == count and len(result.items) == len(rows)


def test_bounds(setup):
    _, read = setup
    for changes in ({'page_size':51}, {'page':-1}, {'expected_revision':True}):
        with pytest.raises(ValueError):
            replace(read, **changes)

publication = load('history_publication', 'services/service-operations/modules/history/publication.py')


def test_contract_fixtures():
    fixtures = load('history_fixtures', 'packages/contracts-service/history/fixtures.py')
    for fixture in (fixtures.SUCCESS, fixtures.DENIED, fixtures.STALE, fixtures.LOST_RESPONSE):
        contract.Result.model_validate(fixture)
    for fixture in (fixtures.PUBLICATION_SUCCESS, fixtures.PUBLICATION_DENIED, fixtures.PUBLICATION_STALE, fixtures.PUBLICATION_LOST_RESPONSE):
        contract.PublicationResult.model_validate(fixture)


def test_owner_publication_subset_and_withdrawal(setup):
    provider, read = setup
    stored = {}
    receipts = {}
    async def owner(_):
        return True
    async def safe(_, job_id):
        source = row()
        return {key:source[key] for key in contract.Entry.model_fields}
    async def commit(command, entries):
        if command.operation_id in receipts:
            previous, result = receipts[command.operation_id]
            return result if previous == command else {'state':'denied'}
        stored[command.watch_id] = entries
        result = {'state':'ready', 'operation_id':str(command.operation_id)}
        receipts[command.operation_id] = (command, result)
        return result
    provider.current_owner, provider.safe_released_job, provider.commit_publication = owner, safe, commit
    reader = model.Reader(provider, contract)
    command = publication.Publication(read.operation_id, read.actor_id, read.subject_id, read.organization_id, read.watch_id, 2, (uid(4),))
    result = asyncio.run(publication.publish(provider, reader, read, command))
    assert result['state'] == 'ready'
    assert len(stored[read.watch_id]) == 1
    assert 'former_owner_name' not in stored[read.watch_id][0]
    assert asyncio.run(publication.publish(provider, reader, read, command)) == result
    assert asyncio.run(publication.publish(provider, reader, read, replace(command, job_ids=())))['state'] == 'denied'
    assert len(stored[read.watch_id]) == 1
    withdrawal = replace(command, operation_id=uid(99), job_ids=())
    asyncio.run(publication.publish(provider, reader, replace(read, operation_id=uid(99)), withdrawal))
    assert stored[read.watch_id] == []
    async def denied(_):
        return False
    provider.current_owner = denied
    assert asyncio.run(publication.publish(provider, reader, read, command))['state'] == 'denied'


def test_publication_rejects_private_fields_and_timeout(setup):
    provider, read = setup
    async def owner(_):
        return True
    async def unsafe(*_):
        return row()
    provider.current_owner, provider.safe_released_job = owner, unsafe
    reader = model.Reader(provider, contract)
    command = publication.Publication(read.operation_id, read.actor_id, read.subject_id, read.organization_id, read.watch_id, 2, (uid(4),))
    assert asyncio.run(publication.publish(provider, reader, read, command))['state'] == 'denied'
    async def timeout(*_):
        raise TimeoutError()
    provider.safe_released_job = timeout
    result = asyncio.run(publication.publish(provider, reader, read, command))
    assert result['state'] == 'pending' and result['operation_id'] == str(read.operation_id)


def test_lookup_rechecks_selected_context(setup):
    provider, read = setup
    run(provider, read)
    reader = model.Reader(provider, contract)
    assert asyncio.run(reader.lookup(read.operation_id, read.actor_id, uid(99), None)) is None
    assert asyncio.run(reader.lookup(read.operation_id, read.actor_id, read.subject_id, uid(99))) is None


def test_publication_lookup_rechecks_owner_and_binding(setup):
    from types import SimpleNamespace
    provider, read = setup
    command = publication.Publication(read.operation_id, read.actor_id, read.subject_id,
        read.organization_id, read.watch_id, 2, ())
    fixtures = load('history_lookup_fixtures', 'packages/contracts-service/history/fixtures.py')
    async def lookup(*_):
        return command, fixtures.PUBLICATION_SUCCESS
    async def owner(_):
        return True
    provider.lookup_publication, provider.current_owner = lookup, owner
    context = SimpleNamespace(actor_id=read.actor_id, subject_id=read.subject_id, organization_id=None)
    reader = model.Reader(provider, contract)
    assert asyncio.run(publication.lookup_publication(provider, reader, read.operation_id, context)).state == 'ready'
    context.organization_id = uid(99)
    assert asyncio.run(publication.lookup_publication(provider, reader, read.operation_id, context)) is None
    context.organization_id = None
    async def revoked(_):
        return False
    provider.current_owner = revoked
    assert asyncio.run(publication.lookup_publication(provider, reader, read.operation_id, context)) is None


def test_route_adapter_binds_context_and_rejects_extra_fields(setup):
    from types import ModuleType, SimpleNamespace
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    package = ModuleType('s12_history')
    package.__path__ = [str(ROOT / 'services/service-operations/modules/history')]
    sys.modules['s12_history'] = package
    sys.modules['s12_history.reader'] = model
    sys.modules['s12_history.publication'] = publication
    routes = load('s12_history.routes', 'services/service-operations/modules/history/routes.py')
    provider, read = setup
    async def context():
        return SimpleNamespace(actor_id=read.actor_id, subject_id=read.subject_id, organization_id=None)
    app = FastAPI()
    app.include_router(routes.build_router(model.Reader(provider, contract), context))
    async def exercise():
      async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get(f'/v1/history/{read.watch_id}', params={'operation_id':str(read.operation_id), 'expected_revision':2})
        assert response.status_code == 200 and response.json()['state'] == 'ready'
        assert (await client.get(f'/v1/history/operations/{read.operation_id}')).json()['actor_id'] == str(read.actor_id)
        assert (await client.get(f'/v1/history/{read.watch_id}', params={'operation_id':str(read.operation_id), 'expected_revision':2, 'page_size':51})).status_code == 422
        assert (await client.post(f'/v1/history/{read.watch_id}/publication', json={'operation_id':str(read.operation_id), 'expected_revision':2, 'job_ids':[], 'private_evidence':'excluded'})).status_code == 422

    asyncio.run(exercise())


def test_publication_replays_receipt_before_changed_source(setup):
    provider, read = setup
    reader = model.Reader(provider, contract)
    command = publication.Publication(read.operation_id, read.actor_id, read.subject_id,
        read.organization_id, read.watch_id, 2, (uid(4),))
    receipts = {}
    calls = []
    allowed = True
    async def owner(_):
        return allowed
    async def lookup(operation_id, actor_id):
        return receipts.get(operation_id)
    async def safe(*_):
        calls.append('source')
        source = row()
        return {key: source[key] for key in contract.Entry.model_fields}
    async def commit(current, entries):
        calls.append('commit')
        receipt = contract.PublicationResult(**read.__dict__, state='ready', revision=2,
            total=0, next_actor='reader').model_dump(mode='json')
        receipts[current.operation_id] = (current, receipt)
        raise TimeoutError()
    provider.current_owner = owner
    provider.lookup_publication = lookup
    provider.safe_released_job = safe
    provider.commit_publication = commit
    assert asyncio.run(publication.publish(provider, reader, read, command))['state'] == 'pending'
    async def changed_source(*_):
        raise ValueError('Work is in rework')
    provider.safe_released_job = changed_source
    restarted = model.Reader(provider, contract)
    expected = receipts[command.operation_id][1]
    assert asyncio.run(publication.publish(provider, restarted, read, command)) == expected
    assert asyncio.run(publication.publish(provider, restarted, read,
        replace(command, job_ids=())))['state'] == 'denied'
    assert calls == ['source', 'commit']
    allowed = False
    assert asyncio.run(publication.publish(provider, restarted, read, command))['state'] == 'denied'
