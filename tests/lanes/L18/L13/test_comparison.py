"""Bounded public contract and route behavior using synthetic sources."""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from services.catalog.modules.comparison.contracts import CompareRequest, Comparison
from services.catalog.modules.comparison.routes import router
from services.catalog.modules.comparison.service import PublicSnapshot, compare

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = json.loads((ROOT / 'packages/contracts-catalog/comparison/fixtures.json').read_text())
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def snapshot(**changes):
    values = dict(listing_id='demo-13', watch_id='physical-13', publication_watch_id='physical-13',
                  availability_watch_id='physical-13', organization_id=None, business_id=None,
                  revision=1, availability_revision=1, business_revision=None, visibility='public',
                  availability='available', business_active=True, checked_at=NOW - timedelta(seconds=1),
                  valid_until=NOW + timedelta(seconds=1), facts=copy.deepcopy(FIXTURES['success']['columns'][0]['facts']))
    values.update(changes)
    return values


class Provider:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def read_public(self, identifier):
        self.calls.append(identifier)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def run(provider, request=None, instant=NOW):
    return asyncio.run(compare('demo-operation-13', CompareRequest.model_validate(request or FIXTURES['request']),
                               provider, lambda: instant))


def test_positive_fixture_and_exact_economics():
    provider = Provider(snapshot())
    result = run(provider)
    assert result.model_dump(mode='json') == FIXTURES['success']
    assert provider.calls == ['demo-13']
    assert result.columns[0].facts.total_minor == 515000
    assert result.columns[0].facts.buyer_fee_minor == 15000


@pytest.mark.parametrize('state', ['success', 'denied', 'stale', 'pending', 'unavailable'])
def test_response_fixtures(state):
    Comparison.model_validate(FIXTURES[state])


@pytest.mark.parametrize('change', [dict(visibility='hidden'), dict(availability='sold'),
                                   dict(availability='removed'), dict(availability='reserved'),
                                   dict(business_active=False), dict(listing_id='another')])
def test_disappeared_or_unavailable_has_no_facts(change):
    result = run(Provider(snapshot(**change))).model_dump_json()
    assert 'Synthetic watch' not in result
    assert json.loads(result)['columns'][0]['state'] == 'unavailable'


def test_missing_is_indistinguishable_from_hidden():
    assert run(Provider(None)).model_dump() == run(Provider(snapshot(visibility='hidden'))).model_dump()


@pytest.mark.parametrize(('offset', 'state'), [(-1, 'available'), (0, 'unavailable'), (1, 'unavailable')])
def test_expiry_before_equal_after(offset, state):
    instant = NOW + timedelta(seconds=1, microseconds=offset)
    assert run(Provider(snapshot()), instant=instant).columns[0].state == state


@pytest.mark.parametrize('change', [dict(organization_id='business-a', business_id='business-b'),
                                   dict(availability_watch_id='another'), dict(publication_watch_id='another'),
                                   dict(checked_at=NOW + timedelta(seconds=2))])
def test_wrong_scope_and_future_source_fail_closed(change):
    assert run(Provider(snapshot(**change))).columns[0].facts is None


def test_revision_changed_requires_explicit_review():
    provider = Provider(snapshot(revision=2))
    assert run(provider).columns[0].state == 'stale'
    request = copy.deepcopy(FIXTURES['request'])
    request['selections'][0]['expected_revision'] = None
    assert run(provider, request).columns[0].state == 'available'


@pytest.mark.parametrize('value', [PermissionError('private contents'), TimeoutError('private contents'),
                                 RuntimeError('private contents')])
def test_denied_and_uncertain_never_echo_source(value):
    result = run(Provider(value))
    assert result.columns[0].state == ('denied' if isinstance(value, PermissionError) else 'pending')
    assert 'private contents' not in result.model_dump_json()
    assert result.columns[0].facts is None


def test_timeout_is_bounded_without_retry():
    class Slow:
        calls = 0

        async def read_public(self, identifier):
            self.calls += 1
            await asyncio.sleep(2)

    provider = Slow()
    assert run(provider).columns[0].state == 'pending'
    assert provider.calls == 1


def test_lost_response_duplicate_and_restart_recheck_current():
    first = run(Provider(snapshot()))
    duplicate = run(Provider(snapshot()))
    assert first == duplicate
    changed = run(Provider(snapshot(visibility='hidden')))
    assert changed.operation_id == first.operation_id
    assert changed.columns[0].facts is None
    assert run(None).columns[0].state == 'pending'


@pytest.mark.parametrize('count', [0, 1, 3])
def test_selection_bounds(count):
    request = {'selections': [{'watch_id': f'watch-{index}'} for index in range(count)]}
    provider = Provider(None)
    assert len(run(provider, request).columns) == count
    assert len(provider.calls) == count


@pytest.mark.parametrize('selections', [[{'watch_id': 'same'}] * 2,
                                      [{'watch_id': f'watch-{index}'} for index in range(4)],
                                      [{'watch_id': '../private'}], [{'watch_id': 'watch', 'expected_revision': True}]])
def test_invalid_selection(selections):
    with pytest.raises(ValidationError):
        CompareRequest(selections=selections)


@pytest.mark.parametrize('field', ['identity', 'evidence_refs', 'serial', 'former_owner'])
def test_private_fields_rejected_at_source_and_request(field):
    values = snapshot()
    values['facts'][field] = 'restricted'
    assert run(Provider(values)).columns[0].state == 'pending'
    with pytest.raises(ValidationError):
        CompareRequest(selections=[], **{field: 'restricted'})


@pytest.mark.parametrize('value', [True, -1, 1.5, float('inf'), 1_000_000_000_001])
def test_invalid_money_is_not_published(value):
    values = snapshot()
    values['facts']['price_minor'] = value
    assert run(Provider(values)).columns[0].facts is None


def test_business_approval_cannot_claim_independent_pass():
    values = snapshot(organization_id='business', business_id='business', business_revision=1)
    values['facts'].update(seller_type='brand', authentication='passed')
    with pytest.raises(ValidationError):
        PublicSnapshot.model_validate(values)


def test_route_missing_provider_and_no_store():
    async def exercise():
        app = FastAPI()
        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.post('/v1/comparison/operations/read-13', json=FIXTURES['request'])
            assert result.status_code == 200
            assert result.headers['cache-control'] == 'no-store'
            assert result.json()['columns'][0]['state'] == 'pending'
            duplicate = {'selections': [{'watch_id': 'same'}] * 2}
            assert (await client.post('/v1/comparison/operations/read-13', json=duplicate)).status_code == 422
    asyncio.run(exercise())


def test_expired_earlier_column_is_removed_at_response_time():
    calls = iter([NOW, NOW + timedelta(seconds=2)])
    result = asyncio.run(compare('read-13', CompareRequest.model_validate(FIXTURES['request']),
                                 Provider(snapshot()), lambda: next(calls)))
    assert result.columns[0].state == 'unavailable'
    assert result.columns[0].facts is None


def test_route_bounds_body_and_never_echoes_private_input():
    async def exercise():
        app = FastAPI()
        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.post('/v1/comparison/operations/read-13',
                                       json={'selections': [], 'evidence': 'restricted-content'})
            assert result.status_code == 422
            assert 'restricted-content' not in result.text
            assert 'اختر' in result.text
            oversized = await client.post('/v1/comparison/operations/read-13', content=b' ' * 4097)
            assert oversized.status_code == 413
            malformed = await client.post('/v1/comparison/operations/read-13', content=b'\xff',
                                          headers={'Content-Type': 'application/json'})
            assert malformed.status_code == 422
            assert malformed.headers['cache-control'] == 'no-store'
            assert 'اختر' in malformed.text
            assert 'error parsing' not in malformed.text
    asyncio.run(exercise())
