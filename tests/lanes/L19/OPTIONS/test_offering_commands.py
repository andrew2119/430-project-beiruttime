import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest
from bt_contracts.catalog.options import OptionWrite
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import CurrentPrincipal

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / 'services/catalog/modules/options/color'
spec = importlib.util.spec_from_file_location('l19_color', MODULE / '__init__.py',
                                              submodule_search_locations=[str(MODULE)])
package = importlib.util.module_from_spec(spec)
sys.modules['l19_color'] = package
routes = importlib.import_module('l19_color.routes')
BRAND = UUID(int=1)
OTHER = UUID(int=2)
ACTOR = UUID(int=3)
OPTION = UUID(int=4)
TEXT = {'en': 'Sample finish', 'ar': 'تشطيب نموذجي'}


class Store:
    def __init__(self):
        self.revision = 0
        self.definitions = []
        self.receipts = {}
        self.events = []

    async def fetchrow(self, query, *args):
        return self.receipts.get(tuple(args))

    async def fetchval(self, query, *args):
        if 'max(revision)' in query:
            return self.revision
        if 'count(' in query:
            return len(self.definitions)
        raise AssertionError(query)

    async def execute(self, query, *args):
        if 'INSERT INTO l10_options' in query:
            self.revision = args[3]
            self.definitions.append(json.loads(args[4]))
        elif 'INSERT INTO l10_operations' in query:
            self.receipts[args[:2]] = {'digest': args[2], 'result': json.loads(args[3])}
        else:
            assert 'pg_advisory_xact_lock' in query


def setup(monkeypatch, kind='color'):
    store = Store()
    access = {'permission': True, 'brand': True, 'business': BRAND, 'timeout': False}

    async def principal(request, organization_id=None):
        if access['timeout']:
            raise PublicError('dependency_unavailable', 'Retry the same operation.', status=503)
        return CurrentPrincipal.model_validate({
            'actor': {'subject_id': str(ACTOR), 'session_id': 'sample',
                      'organization_id': str(access['business'])},
            'organizations': [str(access['business'])],
            'organization_grants': [{'organization_id': str(access['business']),
                                     'permissions': ['business.jobs.write'] if access['permission'] else []}],
        })

    async def brand(request, organization_id):
        if not access['brand']:
            raise PublicError('brand_unavailable', 'Choose an active brand.', status=409)

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield store

    async def enqueue(tx, event, destinations):
        store.events.append(event)

    monkeypatch.setattr(routes.dependencies, 'principal', principal)
    monkeypatch.setattr(routes.dependencies, 'brand', brand)
    monkeypatch.setattr(routes, 'unit_of_work', transaction)
    monkeypatch.setattr(routes, 'enqueue', enqueue)
    module_spec = importlib.util.spec_from_file_location('l19_validator', MODULE.parent / kind / 'schema.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    request = SimpleNamespace(headers={'idempotency-key': 'sample-operation-1'},
                              state=SimpleNamespace(request_id='sample-request'),
                              app=SimpleNamespace(state=SimpleNamespace(pool=None,
                                  hooks={f'catalog.options-{kind}.v1': module.validate})))
    return request, store, access


def body(kind='color', revision=0):
    definitions = {
        'color': dict(color=TEXT, finish=TEXT, swatch='#123456'),
        'material': dict(material=TEXT, grade='316L', construction='solid'),
        'dial': dict(dial=TEXT, hands=TEXT, markers=TEXT, provenance='aftermarket', source_reference='sample'),
        'sophistication': dict(interventions=[TEXT], exclusions=[TEXT], required_tests=[TEXT],
                               price_reference='sample', price_minor=10001, currency='USD'),
    }
    return OptionWrite(expected_revision=revision, component='package' if kind == 'sophistication'
                       else 'dial' if kind == 'dial' else 'case', label=TEXT,
                       base_models=['sample-base'], calibers=['sample-caliber'], details=definitions[kind])


@pytest.mark.parametrize('kind', ['color', 'material', 'dial', 'sophistication'])
def test_save_duplicate_lost_response_and_recovery(monkeypatch, kind):
    request, store, access = setup(monkeypatch, kind)

    async def run():
        first = await routes.publish(BRAND, kind, OPTION, body(kind), request)
        # A lost response is recovered by the original reference, with no second revision or event.
        assert await routes.offering_operation(BRAND, 'sample-operation-1', request) == first
        assert await routes.publish(BRAND, kind, OPTION, body(kind), request) == first
        assert len(store.events) == len(store.definitions) == 1
        assert first['revision'] == 1
        request.headers['idempotency-key'] = 'sample-operation-2'
        second = await routes.publish(BRAND, kind, OPTION, body(kind, 1), request)
        assert second['revision'] == 2
        assert len(store.definitions) == 2
        # Reordered original command retains its original revision.
        request.headers['idempotency-key'] = 'sample-operation-1'
        assert await routes.publish(BRAND, kind, OPTION, body(kind), request) == first
        with pytest.raises(PublicError, match='idempotency_conflict'):
            await routes.publish(BRAND, kind, OPTION, body(kind, 1), request)
        request.headers['idempotency-key'] = 'sample-operation-3'
        with pytest.raises(PublicError, match='stale_option'):
            await routes.publish(BRAND, kind, OPTION, body(kind), request)
        assert len(store.events) == 2
        access['permission'] = False
        with pytest.raises(PublicError, match="offering_denied"):
            await routes.offering_operation(BRAND, 'sample-operation-1', request)
        with pytest.raises(PublicError, match="offering_denied"):
            await routes.publish(BRAND, kind, OPTION, body(kind), request)
    asyncio.run(run())


@pytest.mark.parametrize('case', ['wrong_business', 'revoked', 'timeout'])
def test_current_authority_before_receipt(monkeypatch, case):
    request, store, access = setup(monkeypatch)

    async def run():
        await routes.publish(BRAND, 'color', OPTION, body(), request)
        if case == 'wrong_business':
            access['business'] = OTHER
        elif case == 'revoked':
            access['brand'] = False
        else:
            access['timeout'] = True
        with pytest.raises((AccessDenied, PublicError)):
            await routes.publish(BRAND, 'color', OPTION, body(), request)
        with pytest.raises((AccessDenied, PublicError)):
            await routes.offering_operation(BRAND, 'sample-operation-1', request)
        assert len(store.definitions) == len(store.events) == 1
    asyncio.run(run())


def test_lookup_hides_other_business_and_non_offering_receipts(monkeypatch):
    request, store, _ = setup(monkeypatch)

    async def run():
        for result in [{'brand_id': str(OTHER), 'kind': 'color'}, {'brand_id': str(BRAND)}]:
            store.receipts[(ACTOR, 'sample-operation-1')] = {'result': result}
            with pytest.raises(PublicError, match='operation_unavailable'):
                await routes.offering_operation(BRAND, 'sample-operation-1', request)
        with pytest.raises(PublicError, match='idempotency_required'):
            await routes.offering_operation(BRAND, 'short', request)
    asyncio.run(run())


def test_forms_require_current_scope(monkeypatch):
    request, _, access = setup(monkeypatch)

    async def run():
        assert (await routes.offering_form(BRAND, 'color', request))['dimension'] == 'color'
        access['permission'] = False
        with pytest.raises(PublicError, match="offering_denied"):
            await routes.offering_form(BRAND, 'color', request)
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['color', 'material', 'dial', 'sophistication'])
def test_denied_initial_command_has_no_effect(monkeypatch, kind):
    request, store, access = setup(monkeypatch, kind)
    access['permission'] = False
    with pytest.raises(PublicError, match="offering_denied"):
        asyncio.run(routes.publish(BRAND, kind, OPTION, body(kind), request))
    assert not store.definitions and not store.events and not store.receipts


def test_saved_envelope_binding(monkeypatch):
    request, _, _ = setup(monkeypatch)
    result = asyncio.run(routes.publish(BRAND, 'color', OPTION, body(), request))
    assert {key: result[key] for key in ['schema_version', 'operation_id', 'subject_id', 'watch_id',
                                       'actor_id', 'organization_id', 'expected_revision', 'state',
                                       'revision', 'pending_reason', 'next_actor', 'next_review_at']} == {
        'schema_version': 'catalog.offering-receipt.v1', 'operation_id': 'sample-operation-1',
        'subject_id': str(OPTION), 'watch_id': None, 'actor_id': str(ACTOR),
        'organization_id': str(BRAND), 'expected_revision': 0, 'state': 'saved', 'revision': 1,
        'pending_reason': None, 'next_actor': None, 'next_review_at': None,
    }


def test_legacy_saved_configuration_stays_readable_without_legacy_money():
    from datetime import datetime, timezone
    legacy = body('sophistication').model_dump(mode='json')
    legacy['details']['currency'] = 'LBP'
    legacy['details']['price_minor'] = 87654321
    config = {'id': OPTION, 'owner_id': ACTOR, 'brand_id': BRAND, 'base_model': 'sample-base',
              'caliber': 'sample-caliber', 'revision': 1, 'updated_at': datetime.now(timezone.utc)}

    class Saved:
        async def fetch(self, query, *args):
            if 'FROM l10_selections' in query:
                return [{'kind': 'sophistication', 'component': 'package', 'option_id': OPTION,
                         'option_revision': 1, 'reference_ids': [], 'definition': legacy, 'latest_revision': 1}]
            return []

    result = asyncio.run(routes.snapshot(Saved(), config))
    selected = result['selections'][0]
    assert selected['restricted_legacy'] is True
    assert selected['current'] is False
    assert selected['option_revision'] == 1
    assert selected['definition']['label']['en'] and selected['definition']['label']['ar']
    assert selected['definition']['available'] is False
    assert selected['definition']['details'] == {}
    assert '87654321' not in json.dumps(result) and 'LBP' not in json.dumps(result)
    assert legacy['details']['price_minor'] == 87654321


def test_success_command_matches_published_receipt(monkeypatch):
    request, _, _ = setup(monkeypatch)
    actual = asyncio.run(routes.publish(BRAND, 'color', OPTION, body(), request))
    fixture = json.loads((MODULE / 'fixtures/offering-outcomes.v1.json').read_text())
    expected = next(case['response'] for case in fixture['cases'] if case['name'] == 'success')
    assert actual == expected


@pytest.mark.parametrize('endpoint', ['publish', 'lookup', 'form'])
@pytest.mark.parametrize('failure,status', [
    ('dependency_unavailable', 503), ('unauthorized', 401), ('brand_unavailable', 409),
])
def test_dependency_failures_are_bilingual(monkeypatch, endpoint, failure, status):
    request, store, _ = setup(monkeypatch)

    async def fail(*args, **kwargs):
        raise PublicError(failure, 'Unavailable.', status=status)

    monkeypatch.setattr(routes.dependencies,
                        'brand' if failure == 'brand_unavailable' else 'principal', fail)

    async def run():
        with pytest.raises(PublicError) as caught:
            if endpoint == 'publish':
                await routes.publish(BRAND, 'color', OPTION, body(), request)
            elif endpoint == 'lookup':
                await routes.offering_operation(BRAND, 'sample-operation-1', request)
            else:
                await routes.offering_form(BRAND, 'color', request)
        assert caught.value.code == failure
        assert caught.value.status == status
        assert caught.value.message and caught.value.details['message_ar']
        assert not store.definitions and not store.events and not store.receipts
    asyncio.run(run())


def test_legacy_publication_lookup_and_replay_preserve_stored_bytes(monkeypatch):
    request, store, _ = setup(monkeypatch, 'sophistication')

    async def run():
        original = await routes.publish(BRAND, 'sophistication', OPTION, body('sophistication'), request)
        stored = store.receipts[(ACTOR, 'sample-operation-1')]['result']
        stored['details'].update(currency='LBP', price_minor=87654321)
        historical_body = body('sophistication')
        historical_body.details.update(currency='LBP', price_minor=87654321)
        store.receipts[(ACTOR, 'sample-operation-1')]['digest'] = routes.digest({
            'publish': str(BRAND), 'kind': 'sophistication', 'id': str(OPTION),
            **historical_body.model_dump(mode='json'),
        })
        retained = json.dumps(stored, sort_keys=True)
        for recovered in [
            await routes.offering_operation(BRAND, 'sample-operation-1', request),
            await routes.publish(BRAND, 'sophistication', OPTION, historical_body, request),
        ]:
            assert recovered['restricted_legacy'] is True
            assert recovered['details'] == {}
            assert recovered['available'] is False
            assert recovered['operation_id'] == original['operation_id']
            assert recovered['revision'] == original['revision']
            assert 'LBP' not in json.dumps(recovered)
            assert '87654321' not in json.dumps(recovered)
        assert json.dumps(stored, sort_keys=True) == retained
        assert len(store.definitions) == len(store.events) == 1
        request.headers['idempotency-key'] = 'sample-operation-2'
        with pytest.raises(PublicError, match='invalid_option'):
            await routes.publish(BRAND, 'sophistication', OPTION, historical_body, request)
        assert len(store.definitions) == len(store.events) == len(store.receipts) == 1
    asyncio.run(run())


def test_selection_replay_restricts_legacy_money(monkeypatch):
    from bt_contracts.catalog.options import SelectionWrite
    request, store, _ = setup(monkeypatch)
    selection = SelectionWrite(
        expected_revision=0, brand_id=BRAND, base_model='sample-base',
        caliber='sample-caliber', option_id=OPTION, option_revision=1,
        component='package', reference_ids=[],
    )

    async def buyer(*args, **kwargs):
        return SimpleNamespace(roles=['buyer'], actor=SimpleNamespace(subject_id=ACTOR))

    monkeypatch.setattr(routes.dependencies, 'principal', buyer)
    legacy = body('sophistication').model_dump(mode='json')
    legacy['details'].update(currency='LBP', price_minor=87654321)
    stored = {'revision': 1, 'selections': [
        {'kind': 'sophistication', 'definition': legacy, 'option_revision': 1, 'current': True},
    ]}
    fingerprint = routes.digest({'select': str(OPTION), 'kind': 'sophistication',
                                 **selection.model_dump(mode='json')})
    store.receipts[(ACTOR, 'sample-operation-1')] = {'digest': fingerprint, 'result': stored}
    retained = json.dumps(stored, sort_keys=True)
    result = asyncio.run(routes.select(OPTION, 'sophistication', selection, request))
    assert result['selections'][0]['restricted_legacy'] is True
    assert result['selections'][0]['current'] is False
    assert 'LBP' not in json.dumps(result) and '87654321' not in json.dumps(result)
    assert json.dumps(stored, sort_keys=True) == retained
    assert not store.definitions and not store.events
