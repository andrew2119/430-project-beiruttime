import importlib.util
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import asyncio
from fastapi import HTTPException
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / 'services/trust/modules/passports'
spec = importlib.util.spec_from_file_location('passports', MODULE / 'core.py', submodule_search_locations=[str(MODULE)])
core = importlib.util.module_from_spec(spec)
sys.modules['passports'] = core
sys.modules['passports.core'] = core
spec.loader.exec_module(core)
route_spec = importlib.util.spec_from_file_location('passports.routes', MODULE / 'routes.py')
routes = importlib.util.module_from_spec(route_spec)
route_spec.loader.exec_module(routes)
uid = lambda n: UUID(int=n)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


class Provider:
    def __init__(self, source):
        self.source, self.timeout = source, False
        self.held = False

    @contextmanager
    def guard(self, actor, request, *, timeout):
        assert timeout == 1.2
        if self.timeout:
            raise TimeoutError()
        self.held = True
        try:
            yield self.source
        finally:
            self.held = False


@pytest.fixture
def setup(tmp_path):
    fixture = json.loads((ROOT / 'packages/contracts-trust/passports/fixtures.json').read_text())
    command = core.Issue.model_validate_json(json.dumps(fixture['command']))
    source = core.Source(actor_id=uid(6), subject_id=command.subject_id, organization_id=command.organization_id,
        watch_id=command.watch_id, inspection_id=command.inspection_id, revision=1,
        issuer_id=uid(7), expert_id=uid(8), seller_id=uid(9), inspected_at=NOW,
        completed_at=NOW, assignment_revision=1, custody_receipt_id=uid(10),
        commitment_id=uid(11), quote_id=uid(12), quote_revision=1, policy_revision=1,
        result_revision=1, permitted=True, independent=True, paid_received=True,
        released_completed=True, private_sale=True, passed=True)
    provider = Provider(source)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    def make():
        return core.Passports(str(tmp_path / 'receipts.db'), provider, uid(13), key,
            {uid(13): (uid(7), key.public_key())}, lambda: NOW)
    return make(), provider, command, make


def failure(code, call):
    with pytest.raises(core.Failure) as error:
        call()
    assert error.value.code == code


def test_signed_allowlist_restart_duplicate_and_atomic_outbox(setup):
    service, provider, command, make = setup
    original = service.issue(uid(6), command)
    assert service.verify(original) == original
    assert make().issue(uid(6), command) == original
    assert make().lookup(uid(6), command.operation_id) == original
    assert make().public(original.summary.passport_id) == original
    assert set(original.summary.model_dump()) == {'schema_version','passport_id','issuer_id','inspected_at','issued_at','scope','watch_reference','inspected_revision','claim'}
    assert original.summary.watch_reference != command.watch_id
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM l20_passports').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM l20_passport_outbox').fetchone()[0] == 1
        event = db.execute('SELECT document FROM l20_passport_outbox').fetchone()[0]
        for field in ('seller_id','subject_id','evidence','custody','quote_id','watch_id'):
            assert field not in event


@pytest.mark.parametrize('field,value,code', [
    ('permitted',False,'denied'), ('organization_id',uid(99),'denied'),
    ('actor_id',uid(99),'denied'), ('subject_id',uid(99),'denied'),
    ('revision',2,'stale_revision'), ('independent',False,'inspection_required'),
    ('expert_id',uid(9),'inspection_required'), ('paid_received',False,'inspection_required'),
    ('released_completed',False,'inspection_required'), ('private_sale',False,'inspection_required'),
    ('passed',False,'inspection_required'), ('inspection_id',uid(99),'denied')])
def test_current_source_denials(setup,field,value,code):
    service, provider, command, _ = setup
    provider.source = replace(provider.source, **{field:value})
    failure(code, lambda: service.issue(uid(6), command))
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM l20_passports').fetchone()[0] == 0


@pytest.mark.parametrize('offset,allowed', [(-1,True),(0,True),(1,False)])
def test_utc_before_equal_after(setup,offset,allowed):
    service, provider, command, _ = setup
    provider.source = replace(provider.source, inspected_at=NOW + timedelta(seconds=offset), completed_at=NOW + timedelta(seconds=offset))
    if allowed:
        service.issue(uid(6), command)
    else:
        failure('inspection_required', lambda: service.issue(uid(6), command))


def test_timeout_lost_response_revocation_and_later_modification(setup):
    service, provider, command, make = setup
    provider.timeout = True
    failure('unavailable', lambda: service.issue(uid(6), command))
    provider.timeout = False
    original = make().issue(uid(6), command)
    provider.timeout = True
    failure('unavailable', lambda: make().lookup(uid(6), command.operation_id))
    provider.timeout = False
    provider.source = replace(provider.source, permitted=False)
    failure('denied', lambda: make().issue(uid(6), command))
    failure('denied', lambda: make().lookup(uid(6), command.operation_id))
    provider.source = replace(provider.source, permitted=True, revision=2)
    failure('stale_revision', lambda: make().issue(uid(6), command))
    assert make().public(original.summary.passport_id) == original
    failure('not_found', lambda: make().lookup(uid(99), command.operation_id))


def test_conflicts_and_tampering(setup):
    service, provider, command, _ = setup
    document = service.issue(uid(6), command)
    conflict = command.model_copy(update={'operation_id':uid(55)})
    failure('inspection_already_issued', lambda: service.issue(uid(6), conflict))
    for field,value in [('issuer_id',uid(99)), ('inspected_revision',2), ('inspected_at',NOW-timedelta(days=1)), ('watch_reference',uid(99))]:
        changed = document.model_copy(update={'summary':document.summary.model_copy(update={field:value})})
        failure('invalid_signature', lambda: service.verify(changed))
    failure('invalid_signature', lambda: service.verify(document.model_copy(update={'key_id':uid(99)})))


def test_routes_bound_requests_closed_public_fields_and_safe_errors(setup):
    asyncio.run(route_checks(setup))


async def route_checks(setup):
    service, provider, command, _ = setup
    router = routes.router_for(service, lambda: uid(6))
    endpoints = {r.path:r.endpoint for r in router.routes}

    class Request:
        query_params = {}
        def __init__(self, data):
            self.data = data
        async def stream(self):
            yield self.data

    async def execute(call, action):
        return call(action)

    issue = endpoints['/internal/v1/passports']
    public = endpoints['/public/v1/passports/{passport_id}']
    verify = endpoints['/public/v1/passports/verify']
    with patch('starlette.concurrency.run_in_threadpool', execute):
        response = await issue(Request(command.model_dump_json().encode()), uid(6))
        passport = UUID(response['summary']['passport_id'])
        assert public(passport, Request(b'')) == response
        assert await verify(Request(json.dumps(response).encode())) == response
        expanded = Request(b'')
        expanded.query_params = {'fields':'serial'}
        with pytest.raises(HTTPException) as error:
            public(passport, expanded)
        assert error.value.status_code == 403
        for private in ('full_serial','private_owner','evidence_refs'):
            data = json.loads(json.dumps(response))
            data['summary'][private] = 'restricted'
            with pytest.raises(HTTPException) as error:
                await verify(Request(json.dumps(data).encode()))
            assert error.value.status_code == 422
            assert 'restricted' not in str(error.value.detail)
        with pytest.raises(HTTPException) as error:
            await issue(Request(b'x'*4097), uid(6))
        assert error.value.status_code == 413
        provider.timeout = True
        with pytest.raises(HTTPException) as error:
            await issue(Request(command.model_dump_json().encode()), uid(6))
        assert error.value.status_code == 503


def test_deterministic_wire_fixtures(setup):
    service, _, command, _ = setup
    fixture = json.loads((ROOT / 'packages/contracts-trust/passports/fixtures.json').read_text())
    document = core.Signed.model_validate_json(json.dumps(fixture['signed']))
    assert service.verify(document) == document
    with patch.object(core, 'uuid4', side_effect=[uid(20),uid(21)]):
        issued = service.issue(uid(6), command)
    assert issued.model_dump(mode='json') == fixture['results']['success']['body']
    assert service.lookup(uid(6), command.operation_id).model_dump(mode='json') == fixture['results']['lost_response']['body']
    assert fixture['results']['lost_response']['operation_id'] == str(command.operation_id)
    assert fixture['results']['lost_response']['body'] == fixture['results']['success']['body']
    assert fixture['results']['denied']['body']['detail']['code'] == 'denied'
    assert fixture['results']['stale']['body']['detail']['code'] == 'stale_revision'
    assert fixture['results']['timeout']['body']['detail']['code'] == 'unavailable'


def test_operation_conflict_and_changed_bindings(setup):
    service, provider, command, _ = setup
    service.issue(uid(6), command)
    provider.source = replace(provider.source, watch_id=uid(77))
    failure('operation_conflict', lambda: service.issue(uid(6), command.model_copy(update={'watch_id':uid(77)})))
    provider.source = replace(provider.source, watch_id=command.watch_id, assignment_revision=2)
    failure('stale_revision', lambda: service.issue(uid(6), command))
    failure('stale_revision', lambda: service.lookup(uid(6), command.operation_id))
