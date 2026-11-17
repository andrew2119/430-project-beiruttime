"""Adapter checks use local current-context responses; no connected service is implied."""
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import pytest
from fastapi import HTTPException
from test_decisions import command as make_command

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = 'eligibility_l19_checks'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'services/eligibility/modules/decisions')]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(PACKAGE + '.routes', Path(package.__path__[0]) / 'routes.py')
routes = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = routes
spec.loader.exec_module(routes)


def request(provider=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(eligibility_current=provider)),
                           headers={'authorization': 'Bearer synthetic-access'})


@pytest.mark.asyncio
async def test_missing_current_provider_stays_pending():
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=UUID(int=1)))
    assert await routes.context(request(), UUID(int=2), person) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [{}, {'schema_version': 'obsolete'}, None])
async def test_malformed_current_never_succeeds(value):
    async def provider(*args):
        return value
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=UUID(int=1)))
    assert await routes.context(request(provider), UUID(int=2), person) is None


@pytest.mark.asyncio
async def test_timeout_current_never_succeeds():
    async def provider(*args):
        raise TimeoutError
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=UUID(int=1)))
    assert await routes.context(request(provider), UUID(int=2), person) is None


def test_business_permission_never_carries_between_businesses():
    from bt_runtime.principal import CurrentPrincipal
    principal = CurrentPrincipal.model_validate({'actor': {'subject_id': str(UUID(int=1)), 'session_id': str(UUID(int=2)),
        'organization_id': str(UUID(int=3))}, 'permissions': ['eligibility.grants.consume'],
        'organizations': [str(UUID(int=3))], 'organization_grants': [{'organization_id': str(UUID(int=3)),
        'permissions': ['eligibility.grants.consume']}]})
    routes.allowed(principal, {'brand_id': UUID(int=3)}, 'eligibility.grants.consume')
    from bt_contracts_core.errors import AccessDenied
    with pytest.raises(AccessDenied):
        routes.allowed(principal, {'brand_id': UUID(int=4)}, 'eligibility.grants.consume')


@pytest.mark.asyncio
async def test_current_identity_change_denies(monkeypatch):
    async def current(*args):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=UUID(int=99), session_id=UUID(int=2)))
    monkeypatch.setattr(routes, 'require_principal', lambda incoming: SimpleNamespace(subject=str(UUID(int=1)), session_id=UUID(int=2)))
    monkeypatch.setattr(routes, 'current_principal', current)
    incoming=request()
    incoming.app.state.identity=object()
    incoming.state=SimpleNamespace(request_id='synthetic-check')
    with pytest.raises(HTTPException) as failure:
        await routes.principal(incoming)
    assert failure.value.status_code == 403



class LocalRows:
    def __init__(self, consent):
        self.consent = consent
        self.operations = {}
        self.state = None
        self.events = []

    async def fetchrow(self, query, *args):
        if 'FROM eligibility_consents' in query:
            return self.consent
        if 'FROM eligibility_decision_operations' in query:
            return self.operations.get(args[0])
        raise AssertionError(query)

    async def fetchval(self, query, *args):
        assert 'FROM eligibility_decision_states' in query and 'FOR UPDATE' in query
        return self.state

    async def execute(self, query, *args):
        import json
        if query.startswith('INSERT INTO eligibility_decision_states'):
            if self.state is None:
                self.state = json.dumps({'revision': 0, 'reviews': [], 'grants': []})
        elif query.startswith('UPDATE eligibility_decision_states'):
            self.state = args[1]
        elif query.startswith('INSERT INTO eligibility_decision_operations'):
            self.operations[args[0]] = dict(actor_id=args[1], consent_id=args[2], digest=args[3], permission=args[4], result=args[5])
        else:
            raise AssertionError(query)


@pytest.fixture
def adapter(monkeypatch, current, consent):
    from contextlib import asynccontextmanager
    from copy import deepcopy
    rows = LocalRows(consent)
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=UUID(current['reviewer_id'])))
    async def identity(incoming):
        return person
    async def provider(*args):
        return current
    @asynccontextmanager
    async def transaction(*args, **kwargs):
        before = deepcopy(rows.__dict__)
        try:
            yield rows
        except BaseException:
            rows.__dict__ = before
            raise
    async def enqueue(tx, event, destinations):
        tx.events.append(event.model_dump(mode='json'))
    monkeypatch.setattr(routes, 'principal', identity)
    monkeypatch.setattr(routes, 'allowed', lambda *args: None)
    monkeypatch.setattr(routes, 'unit_of_work', transaction)
    monkeypatch.setattr(routes, 'enqueue', enqueue)
    incoming = request(provider)
    incoming.app.state.pool = object()
    incoming.state = SimpleNamespace(request_id='synthetic-receipt-check')
    return rows, incoming, current


@pytest.mark.asyncio
async def test_durable_receipt_duplicate_conflict_and_revoked_replay(adapter):
    import json
    rows, incoming, current = adapter
    body = routes.Command.model_validate(make_command('review', verdict='eligible'))
    result = await routes.command(body, incoming)
    routes.schema.Result.model_validate(result)
    # Rehydrate persisted JSON before the lost-response retry.
    rows.state = json.dumps(json.loads(rows.state))
    assert await routes.command(body, incoming) == result
    assert len(rows.events) == len(rows.operations) == 1
    assert 'Synthetic identity criteria checked.' not in json.dumps(rows.events)
    conflicting = body.model_copy(update={'verdict': 'correction'})
    with pytest.raises(HTTPException) as conflict:
        await routes.command(conflicting, incoming)
    assert conflict.value.status_code == 409
    current['assignment_current'] = False
    with pytest.raises(HTTPException) as denied:
        await routes.command(body, incoming)
    assert denied.value.status_code == 403
    assert len(rows.events) == 1


@pytest.mark.asyncio
async def test_pending_retry_same_reference_does_not_seed_success(adapter):
    rows, incoming, current = adapter
    provider = incoming.app.state.eligibility_current
    incoming.app.state.eligibility_current = None
    body = routes.Command.model_validate(make_command('review', verdict='eligible'))
    with pytest.raises(HTTPException) as pending:
        await routes.command(body, incoming)
    assert pending.value.status_code == 503
    assert not rows.operations and rows.state is None and not rows.events
    incoming.app.state.eligibility_current = provider
    assert (await routes.command(body, incoming))['state'] == 'eligible'


@pytest.mark.asyncio
async def test_failed_outbox_rolls_back_state_and_receipt(adapter, monkeypatch):
    rows, incoming, current = adapter
    async def fail(*args):
        raise OSError('Synthetic interrupted write')
    monkeypatch.setattr(routes, 'enqueue', fail)
    body = routes.Command.model_validate(make_command('review', verdict='eligible'))
    with pytest.raises(OSError):
        await routes.command(body, incoming)
    assert rows.state is None and not rows.operations and not rows.events


@pytest.mark.asyncio
@pytest.mark.parametrize('recovery', ['replay', 'lookup'])
@pytest.mark.parametrize('instant,valid', [('12:59:59', True), ('13:00:00', False), ('13:00:01', False)])
async def test_receipt_recovery_requires_unexpired_access(adapter, recovery, instant, valid):
    from contextlib import asynccontextmanager
    from copy import deepcopy
    rows, incoming, current = adapter
    body = routes.Command.model_validate(make_command('review', verdict='eligible'))
    receipt = await routes.command(body, incoming)
    before = deepcopy(rows.__dict__)

    @asynccontextmanager
    async def acquire():
        yield rows

    incoming.app.state.pool = SimpleNamespace(acquire=acquire)
    current['now'] = '2026-11-16T' + instant + '+00:00'

    async def recover():
        if recovery == 'replay':
            return await routes.command(body, incoming)
        return await routes.lookup(body.operation_id, incoming)

    if valid:
        assert await recover() == receipt
    else:
        with pytest.raises(HTTPException) as denied:
            await recover()
        assert denied.value.status_code == 403
        # Renewed current access can retrieve the original historical receipt.
        current['expires_at'] = '2026-11-16T14:00:00+00:00'
        assert await recover() == receipt
    assert rows.__dict__ == before


@pytest.mark.asyncio
@pytest.mark.parametrize('instant,valid', [('12:59:59', True), ('13:00:00', False), ('13:00:01', False)])
async def test_new_revoke_checks_permission_expiry(adapter, instant, valid):
    import json
    from test_decisions import prepared
    rows, incoming, current = adapter
    state = prepared(current, rows.consent)
    rows.state = json.dumps(state)
    rows.consent['status'] = 'withdrawn'
    current['now'] = '2026-11-16T' + instant + '+00:00'
    body = routes.Command.model_validate(make_command('revoke', 2, grant_id=state['grants'][0]['grant_id']))
    result = await routes.command(body, incoming)
    routes.schema.Result.model_validate(result)
    persisted = json.loads(rows.state)
    if valid:
        assert result['state'] == 'revoked'
        assert persisted['revision'] == 3
        from datetime import datetime
        assert datetime.fromisoformat(persisted['grants'][0]['revoked_at']) == datetime.fromisoformat(current['now'])
    else:
        assert result['state'] == 'denied'
        assert result['reason_code'] == 'permission_expired'
        assert persisted == state
    assert len(rows.operations) == len(rows.events) == 1
