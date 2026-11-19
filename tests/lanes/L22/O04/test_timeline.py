import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / 'services/communications/modules/order-timeline'
spec = importlib.util.spec_from_file_location('l22_timeline', MODULE / 'projection.py', submodule_search_locations=[str(MODULE)])
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
sys.modules[spec.name + '.projection'] = m
route_spec = importlib.util.spec_from_file_location('l22_timeline.routes', MODULE / 'routes.py')
routes = importlib.util.module_from_spec(route_spec)
route_spec.loader.exec_module(routes)
FIXTURE = json.loads((ROOT / 'packages/contracts-comms/order-timeline/fixtures.json').read_text())
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


class Access:
    revoked = False
    denied = False

    async def authorize(self, credential, order_id, organization_id):
        if self.denied or credential not in ('Bearer buyer', 'Bearer seller', 'Bearer staff'):
            raise m.Denied()
        if order_id != 'order-1' or (credential == 'Bearer staff') != (organization_id == 'business-1'):
            raise m.Denied()
        return m.Lease(credential.split()[1], organization_id, order_id, 'watch-1', 1,
                       tuple((name, 1) for name in m.SOURCES))

    async def recheck(self, credential, lease):
        return not self.revoked

    async def catalog(self, credential, organization_id, offset, limit):
        if credential != 'Bearer buyer' or organization_id is not None:
            raise m.Denied()
        return {'total': 1000, 'items': [{'order_id': f'order-{i}', 'reference': f'BT-{i}'}
                                       for i in range(offset, min(offset + limit, 1000))]}


class Source:
    def __init__(self, value):
        self.value = copy.deepcopy(value)
        self.calls = 0
        self.delay = 0

    async def snapshot(self, lease):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return copy.deepcopy(self.value)


def service():
    access = Access()
    sources = {name: Source(value) for name, value in FIXTURE['sources'].items()}
    return m.TimelineService(access, sources, lambda: NOW), access, sources


def run(coro):
    return asyncio.run(coro)


def test_success_both_parties_restart_duplicate_and_privacy():
    subject, _, sources = service()
    buyer = run(subject.read('Bearer buyer', 'order-1'))
    assert buyer == run(subject.read('Bearer seller', 'order-1'))
    assert buyer == run(subject.read('Bearer buyer', 'order-1'))
    restarted, _, _ = service()
    assert buyer == run(restarted.read('Bearer buyer', 'order-1'))
    assert buyer == FIXTURE['success']
    assert all(source.calls == 3 for source in sources.values())
    sources['custody'].value['evidence_refs'] = ['private-file']
    sources['orders'].value['private_notes'] = 'secret'
    assert 'private-file' not in json.dumps(run(subject.read('Bearer buyer', 'order-1')))
    assert 'secret' not in json.dumps(run(subject.read('Bearer buyer', 'order-1')))


@pytest.mark.parametrize('credential,org', [('Bearer stranger', None), ('Bearer staff', None), ('Bearer staff', 'other'), ('Bearer buyer', 'business-1')])
def test_current_scope_denied(credential, org):
    subject, _, sources = service()
    with pytest.raises(m.Denied):
        run(subject.read(credential, 'order-1', org))
    assert not any(source.calls for source in sources.values())


def test_current_assignment_revocation_discards_answer():
    subject, access, _ = service()
    access.revoked = True
    with pytest.raises(m.Denied):
        run(subject.read('Bearer buyer', 'order-1'))
    access.revoked = False
    assert run(subject.read('Bearer staff', 'order-1', 'business-1'))['order_id'] == 'order-1'


@pytest.mark.parametrize('source', m.SOURCES[1:])
@pytest.mark.parametrize('field,value', [('revision', 0), ('revision', 2), ('order_id', 'other'), ('watch_id', 'other'), ('occurred_at', '2026-11-17T00:00:00Z'), ('quote_revision', 2), ('state', 'paid_out')])
def test_reordered_stale_mismatched_sources_never_invent_success(source, field, value):
    subject, _, sources = service()
    sources[source].value[field] = value
    answer = run(subject.read('Bearer buyer', 'order-1'))
    row = next(row for row in answer['milestones'] if row['source'] == source)
    assert row['state'] == 'unavailable'
    assert row['amount_minor'] is None


def test_partial_timeout_and_missing_source():
    subject, _, sources = service()
    sources['payments'].delay = .4
    del sources['progress']
    answer = run(subject.read('Bearer buyer', 'order-1'))
    assert answer['milestones'][1]['state'] == 'unavailable'
    assert answer['milestones'][4]['state'] == 'unavailable'
    assert answer['milestones'][3]['state'] == 'pending'


@pytest.mark.parametrize('hours,delta,expected', [(24,-1,'scheduled'),(24,0,'due'),(24,1,'due'),(48,-1,'due'),(48,0,'escalated'),(48,1,'escalated')])
def test_follow_up_boundaries(hours, delta, expected):
    subject, _, _ = service()
    subject.clock = lambda: NOW + timedelta(hours=hours, seconds=delta)
    assert run(subject.read('Bearer buyer','order-1'))['waiting']['follow_up'] == expected


@pytest.mark.parametrize('value', [True, -1, 1.5, float('inf'), 9007199254740992])
def test_invalid_economics_fail_closed(value):
    subject, _, sources = service()
    sources['orders'].value['economics']['total_minor'] = value
    with pytest.raises(m.Unavailable):
        run(subject.read('Bearer buyer', 'order-1'))


def test_orders_outage_never_draws_partial_authority():
    subject, _, sources = service()
    sources['orders'].value['revision'] = 2
    with pytest.raises(m.Unavailable):
        run(subject.read('Bearer buyer','order-1'))


def test_complete_server_pagination_and_bounds():
    subject, _, _ = service()
    rows = []
    for offset in range(0, 1000, 20):
        page = run(subject.list('Bearer buyer', offset=offset))
        assert page['total'] == 1000
        rows.extend(page['items'])
    assert len({row['order_id'] for row in rows}) == 1000
    assert run(subject.list('Bearer buyer', offset=1000))['items'] == []
    for limit in [0, 21, True]:
        with pytest.raises(ValueError):
            run(subject.list('Bearer buyer', limit=limit))


def test_route_statuses_no_store_and_retry():
    subject, access, sources = service()
    app = FastAPI()
    app.include_router(routes.create_router(subject))

    async def journey():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/v1/order-timeline/order-1')).status_code == 401
            denied = await client.get('/v1/order-timeline/order-1', headers={'Authorization': 'Bearer stranger'})
            assert denied.status_code == 403 and 'watch-1' not in denied.text
            headers = {'Authorization': 'Bearer buyer'}
            sources['orders'].delay = .4
            assert (await client.get('/v1/order-timeline/order-1', headers=headers)).status_code == 503
            sources['orders'].delay = 0
            response = await client.get('/v1/order-timeline/order-1', headers=headers)
            assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
            assert (await client.get('/v1/order-timeline?limit=21', headers=headers)).status_code == 422
            access.revoked = True
            assert (await client.get('/v1/order-timeline/order-1', headers=headers)).status_code == 403
    run(journey())


def test_malformed_authority_never_grants_access():
    subject, access, _ = service()

    async def malformed(credential, lease):
        return 'denied'

    access.recheck = malformed
    with pytest.raises(m.Denied):
        run(subject.read('Bearer buyer', 'order-1'))


def test_oversized_catalog_is_rejected_before_processing():
    subject, access, _ = service()

    async def malformed(*args):
        return {'total': 1000, 'items': [None] * 1000}

    access.catalog = malformed
    with pytest.raises(m.Unavailable):
        run(subject.list('Bearer buyer'))


def test_boolean_quote_revision_is_not_current():
    subject, _, sources = service()
    sources['payments'].value['quote_revision'] = True
    assert run(subject.read('Bearer buyer', 'order-1'))['milestones'][1]['state'] == 'unavailable'


def test_completion_of_source_calls_out_of_order_preserves_milestones():
    subject, _, sources = service()
    expected = run(subject.read('Bearer buyer', 'order-1'))
    for index, source in enumerate(sources.values()):
        source.delay = (6-index) / 1000
    assert run(subject.read('Bearer seller', 'order-1')) == expected


def test_published_schema_has_unique_required_fields_and_resolved_definitions():
    schema = json.loads((ROOT / 'packages/contracts-comms/order-timeline/schema.json').read_text())

    def walk(value):
        if isinstance(value, dict):
            if 'required' in value:
                assert len(value['required']) == len(set(value['required']))
                if 'properties' in value:
                    assert set(value['required']) <= set(value['properties'])
            if '$ref' in value:
                assert value['$ref'].removeprefix('#/$defs/') in schema['$defs']
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(schema)


@pytest.mark.parametrize('field,value', [('quote_id', 'quote-other'), ('quote_revision', 2)])
def test_orders_retained_quote_binding_must_match(field, value):
    subject, _, sources = service()
    sources['orders'].value['economics'][field] = value
    with pytest.raises(m.Unavailable):
        run(subject.read('Bearer buyer', 'order-1'))


@pytest.mark.parametrize('state', ['pending', 'confirmed', 'blocked'])
def test_financial_facts_preserve_state_amount_and_operation(state):
    subject, _, sources = service()
    row = dict(FIXTURE['refund_pending'], state=state)
    sources['settlement'].value['financial'] = [row]
    answer = run(subject.read('Bearer buyer', 'order-1'))
    assert answer['financial'] == [row]
    assert answer['milestones'][5]['state'] == 'pending'
    sources['settlement'].value['revision'] = 2
    assert run(subject.read('Bearer buyer', 'order-1'))['financial'] == []


@pytest.mark.parametrize('field,value', [('amount_minor', True), ('state', 'authorized'), ('source', 'payments'), ('occurred_at', '2026-11-17T00:00:00Z')])
def test_malformed_financial_facts_make_source_unavailable(field, value):
    subject, _, sources = service()
    sources['settlement'].value['financial'] = [dict(FIXTURE['refund_pending'], **{field: value})]
    answer = run(subject.read('Bearer buyer', 'order-1'))
    assert answer['financial'] == []
    assert answer['milestones'][5]['state'] == 'unavailable'
