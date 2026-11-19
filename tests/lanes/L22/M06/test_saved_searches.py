import asyncio
import copy
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
from pathlib import Path
import httpx
import pytest
from fastapi import FastAPI
from bt_contracts.comms.saved_searches.models import Command, Criteria, Publication
from bt_contracts_core.errors import PublicError
from bt_bulkheads import DependencyClient
from saved_search_module import service, routes
from fakes import Catalog, Store, Pool, NOW

OWNER = UUID('11111111-1111-4111-8111-111111111111')
OTHER = UUID('22222222-2222-4222-8222-222222222222')


def command(**patch):
    return Command(operation_id=uuid4(), subject_id=uuid4(), expected_revision=0,
                   name='ساعة Cedar ⌚', criteria=Criteria(), alerts_enabled=True, **patch)


def publication(at=NOW):
    return Publication(occurrence_id=uuid4(), listing_id=uuid4(), watch_id=uuid4(), revision=2, published_at=at, sample=True)


@pytest.mark.asyncio
async def test_empty_search_durable_receipt_replay_conflict_stale_and_private_owner():
    store, catalog, body = Store(), Catalog(), command()
    first = await service.command(store, OWNER, body, catalog)
    assert first['state'] == 'saved' and first['result']['criteria']['q'] == ''
    # Recreate the service-facing objects over retained storage after response loss.
    restarted = Store()
    restarted.__dict__.update(copy.deepcopy(store.__dict__))
    catalog.broken = True
    assert await service.command(restarted, OWNER, body, catalog) == first
    with pytest.raises(PublicError, match='operation_conflict'):
        await service.command(store, OWNER, body.model_copy(update={'name': 'Changed'}), catalog)
    with pytest.raises(PublicError, match='stale_revision'):
        await service.command(store, OWNER, body.model_copy(update={'operation_id': uuid4()}), catalog)
    with pytest.raises(PublicError, match='not_found'):
        await service.command(store, OTHER, body.model_copy(update={'expected_revision': 1}), catalog)
    catalog.broken = False
    with pytest.raises(PublicError, match='not_found'):
        await service.command(store, OTHER, body, catalog)
    assert len(store.searches) == 1 and first['actor_id'] == str(OWNER)


@pytest.mark.asyncio
@pytest.mark.parametrize('delta,expected', [(-1, 0), (0, 1), (1, 1)])
async def test_new_publication_before_equal_after_eligibility(delta, expected):
    store, catalog = Store(), Catalog()
    await service.command(store, OWNER, command(), catalog)
    event = publication(NOW + timedelta(microseconds=delta))
    store.now = NOW + timedelta(seconds=1)
    await service.deliver(store, OWNER, event, catalog)
    await service.deliver(store, OWNER, event, catalog)
    assert len(store.notices) == expected
    if expected:
        assert next(iter(store.notices.values()))['sample'] is True
        assert len(catalog.calls) == 1
    else:
        assert catalog.calls == []


@pytest.mark.asyncio
async def test_opt_out_reenable_edit_remove_and_no_broad_delivery():
    store, catalog = Store(), Catalog()
    body = command()
    await service.command(store, OWNER, body, catalog)
    await service.command(store, OTHER, command(), catalog)
    off = body.model_copy(update={'operation_id': uuid4(), 'expected_revision': 1, 'alerts_enabled': False})
    await service.command(store, OWNER, off, catalog)
    await service.deliver(store, OWNER, publication(), catalog)
    assert not store.notices
    store.now += timedelta(seconds=1)
    on = off.model_copy(update={'operation_id': uuid4(), 'expected_revision': 2, 'alerts_enabled': True})
    await service.command(store, OWNER, on, catalog)
    await service.deliver(store, OWNER, publication(), catalog)
    assert not store.notices
    event = publication(store.now)
    await service.deliver(store, OWNER, event, catalog)
    assert len(store.notices) == 1 and all(r['owner_id'] == OWNER for r in store.notices.values())
    remove = on.model_copy(update={'operation_id': uuid4(), 'expected_revision': 3, 'kind': 'remove'})
    assert (await service.command(store, OWNER, remove, catalog))['state'] == 'removed'
    with pytest.raises(PublicError, match='stale_revision'):
        await service.command(store, OWNER, on.model_copy(update={'operation_id': uuid4(), 'expected_revision': 4}), catalog)


@pytest.mark.asyncio
async def test_provider_timeout_malformed_bindings_nonmatch_and_conflicting_replay():
    store, catalog, body = Store(), Catalog(), command()
    catalog.broken = True
    with pytest.raises(PublicError):
        await service.command(store, OWNER, body, catalog)
    assert not store.searches and not store.operations
    catalog.broken = False
    await service.command(store, OWNER, body, catalog)
    event = publication()
    catalog.broken = True
    with pytest.raises(PublicError):
        async with store.transaction():
            await service.deliver(store, OWNER, event, catalog)
    assert not store.notices and not store.deliveries
    catalog.broken = False
    catalog.answer = False
    await service.deliver(store, OWNER, event, catalog)
    assert not store.notices
    with pytest.raises(PublicError, match='occurrence_conflict'):
        await service.deliver(store, OWNER, event.model_copy(update={'revision': 3}), catalog)
    catalog.answer = True
    catalog.public = False
    await service.deliver(store, OWNER, publication(), catalog)
    assert not store.notices
    async def mismatched(*args):
        return {'criteria': Criteria(q='changed'), 'semantics_revision': 'canonical-v1'}
    catalog.validate = mismatched
    with pytest.raises(PublicError):
        await service.command(store, OWNER, command(), catalog)
    async def wrong_match(pub, criteria, revision):
        result = await Catalog().match(pub, criteria, revision)
        return result.model_copy(update={'listing_id': uuid4()})
    catalog.match = wrong_match
    with pytest.raises(PublicError):
        await service.deliver(store, OWNER, publication(), catalog)


@pytest.mark.asyncio
async def test_actual_dependency_deadline_and_future_publication():
    async def slow(*args):
        await asyncio.sleep(10)
    catalog = Catalog()
    catalog.validate = slow
    with pytest.raises(PublicError):
        await service.validate(catalog, Criteria())
    with pytest.raises(PublicError):
        await service.deliver(Store(), OWNER, publication(NOW + timedelta(seconds=1)), Catalog())


@pytest.mark.parametrize('patch', [dict(min_minor=2, max_minor=1), dict(min_minor=-1), dict(max_minor=1.5), dict(min_minor=True), dict(max_minor=9000000000000001), dict(q=' '.join(['word'] * 9)), dict(sale_mode='unknown'), dict(currency='EUR'), dict(private_evidence='hidden')])
def test_invalid_criteria_never_saved(patch):
    with pytest.raises((ValueError, PublicError)):
        Criteria(**patch)


@pytest.mark.asyncio
async def test_scope_rechecked_on_every_read_and_receipt_lookup():
    store = Store()
    catalog = Catalog()
    body = command()
    await service.command(store, OWNER, body, catalog)
    state = {'owner': OWNER, 'organization': None, 'roles': ['buyer']}
    def identity(_):
        return httpx.Response(200, json={'actor': {'subject_id': str(state['owner']), 'session_id': 'test', 'organization_id': state['organization']}, 'roles': state['roles']})
    app = FastAPI()
    app.state.pool = Pool(store)
    app.state.identity = DependencyClient('identity', 'http://identity', transport=httpx.MockTransport(identity))
    @app.middleware('http')
    async def context(request, call_next):
        request.state.request_id = 'test-request'
        return await call_next(request)
    @app.exception_handler(PublicError)
    async def errors(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse({'code': error.code}, status_code=error.status)
    from fastapi import HTTPException
    @app.exception_handler(HTTPException)
    async def denied_errors(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse({'code': 'forbidden' if error.status_code == 403 else 'unauthorized'}, status_code=error.status_code)
    app.include_router(routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer synthetic'}) as client:
        assert (await client.get('/v1/saved-searches')).json()['total'] == 1
        assert (await client.get('/v1/saved-searches/operations/' + str(body.operation_id))).status_code == 200
        oversized = await client.post('/v1/saved-searches/commands', content=b' ' * 8193, headers={'Content-Type':'application/json'})
        assert oversized.status_code == 413
        invalid = body.model_dump(mode='json')
        for values, code in [({'min_minor': 2, 'max_minor': 1}, 'invalid_range'), ({'min_minor': True}, 'invalid_range'), ({'q': ' '.join(['word'] * 9)}, 'invalid_filters'), ({'q': 'x' * 161}, 'invalid_filters'), ({'brand': 'x' * 101}, 'invalid_filters'), ({'model': 'x' * 161}, 'invalid_filters'), ({'location': 'x' * 161}, 'invalid_filters'), ({'sale_mode': 'invalid'}, 'invalid_filters'), ({'sort': 'invalid'}, 'invalid_filters')]:
            invalid['criteria'] = values
            response = await client.post('/v1/saved-searches/commands', json=invalid)
            assert response.status_code == 422 and response.json()['code'] == code
        state['owner'] = OTHER
        assert (await client.get('/v1/saved-searches/operations/' + str(body.operation_id))).status_code == 404
        assert (await client.get('/v1/saved-searches')).json()['total'] == 0
        denied_fixture = json.loads((Path(__file__).resolve().parents[4] / 'packages/contracts-comms/saved-searches/fixtures.json').read_text())['cases'][1]
        state['organization'] = denied_fixture['organization_id']
        denied_response = await client.post('/v1/saved-searches/commands', json=denied_fixture['request'])
        assert denied_response.status_code == denied_fixture['expected_status']
        assert denied_response.json() == denied_fixture['expected']
        assert (await client.get('/v1/saved-searches')).status_code == 403
        state.update(organization=None, roles=['operator'])
        assert (await client.get('/v1/saved-searches')).status_code == 403
    await app.state.identity.aclose()


@pytest.mark.asyncio
async def test_thousand_notice_pagination_totals_and_read_clear_visibility():
    store, catalog = Store(), Catalog()
    body = command()
    await service.command(store, OWNER, body, catalog)
    for _ in range(1000):
        await service.deliver(store, OWNER, publication(), catalog)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=Pool(store), saved_search_catalog=catalog)))
    rows = []
    for offset in range(0, 1000, 20):
        result = await routes.page(request, OWNER, offset, 20, True)
        assert result['total'] == 1000 and len(result['items']) == 20
        rows += result['items']
    assert len({r['id'] for r in rows}) == 1000
    row = next(iter(store.notices.values()))
    assert (await routes.destination(row['id'], request, OWNER))['href'].startswith('/watches/')
    catalog.public = False
    with pytest.raises(PublicError):
        await routes.destination(row['id'], request, OWNER)
    # Direct mutation uses the same idempotent bit even after a lost response.
    await store.execute('UPDATE l22_match_notices SET read=true', row['id'], OWNER)
    assert store.notices[row['id']]['read'] and not store.notices[row['id']]['cleared']
    assert (await routes.page(request, OWNER, 0, 20, True))['total'] == 1000


@pytest.mark.asyncio
async def test_published_deterministic_envelopes_are_executable():
    root = Path(__file__).resolve().parents[4]
    fixtures = json.loads((root / 'packages/contracts-comms/saved-searches/fixtures.json').read_text())
    positive = fixtures['cases'][0]
    store = Store()
    body = Command.model_validate(positive['request'])
    owner = UUID(positive['actor_id'])
    assert await service.command(store, owner, body, Catalog()) == positive['expected']
    lost = fixtures['cases'][3]
    assert await service.command(store, owner, Command.model_validate(lost['request']), None) == lost['expected']
    stale = fixtures['cases'][2]
    store.searches[body.subject_id]['revision'] = 2
    with pytest.raises(PublicError, match=stale['expected']['code']):
        await service.command(store, owner, Command.model_validate(stale['request']), Catalog())
    invalid = fixtures['cases'][4]
    with pytest.raises(PublicError, match=invalid['expected']['code']):
        Command.model_validate(invalid['request'])
    from bt_contracts.comms.saved_searches.models import Match, Validation
    Validation.model_validate(fixtures['provider']['validation'])
    for name in ('positive_match', 'negative_match', 'stale_match'):
        Match.model_validate(fixtures['provider'][name])


@pytest.mark.asyncio
async def test_authenticated_event_adapter_targeting_replay_and_wrong_producer(monkeypatch):
    from fastapi import HTTPException
    from bt_contracts_core.models import EventEnvelope
    from saved_search_module import events
    store, catalog = Store(), Catalog()
    await service.command(store, OWNER, command(), catalog)
    await service.command(store, OTHER, command(), catalog)
    settings = SimpleNamespace(service_auth_public_key='synthetic-verification-reference', auth_issuer='synthetic-issuer', service_name='communications')
    request = SimpleNamespace(headers={'Authorization': 'Bearer synthetic'}, app=SimpleNamespace(state=SimpleNamespace(settings=settings, pool=Pool(store), saved_search_catalog=catalog)))
    claims = {'type': 'service', 'sub': 'catalog'}
    def verified(token, public_key, **options):
        assert token == 'synthetic' and options['audience'] == 'communications' and options['algorithms'] == ['RS256']
        return claims
    monkeypatch.setattr(events.jwt, 'decode', verified)
    published = publication()
    def envelope(owner):
        return EventEnvelope(type='catalog.listing-published.v1', source='catalog', subject=str(published.listing_id), time=published.published_at, request_id='synthetic-event', data={**published.model_dump(mode='json'), 'recipient_id': str(owner)})
    first = envelope(OWNER)
    await events.events(first, request)
    await events.events(first, request)
    assert len(store.notices) == 1
    await events.events(envelope(OTHER), request)
    assert len(store.notices) == 2
    claims['sub'] = 'orders'
    with pytest.raises(HTTPException) as denied:
        await events.events(first, request)
    assert denied.value.status_code == 403
    request.headers = {}
    with pytest.raises(HTTPException) as missing:
        await events.events(first, request)
    assert missing.value.status_code == 401


@pytest.mark.asyncio
async def test_full_subscription_delivery_with_slow_valid_matches_and_stable_retry(monkeypatch):
    from bt_contracts_core.models import EventEnvelope
    from saved_search_module import events
    store, catalog = Store(), Catalog()
    for _ in range(100):
        await service.command(store, OWNER, command(), catalog)
    active = peak = 0
    original = catalog.match

    async def slow_match(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.45)
            return await original(*args)
        finally:
            active -= 1

    catalog.match = slow_match
    monkeypatch.setattr(events.jwt, 'decode', lambda *args, **kwargs: {'type': 'service', 'sub': 'catalog'})
    settings = SimpleNamespace(service_auth_public_key='synthetic-reference', auth_issuer='synthetic', service_name='communications')
    request = SimpleNamespace(headers={'Authorization': 'Bearer synthetic'}, app=SimpleNamespace(state=SimpleNamespace(settings=settings, pool=Pool(store), saved_search_catalog=catalog)))
    published = publication()
    event = EventEnvelope(type='catalog.listing-published.v1', source='catalog', subject=str(published.listing_id), time=published.published_at, request_id='synthetic-event', data={**published.model_dump(mode='json'), 'recipient_id': str(OWNER)})
    await events.events(event, request)
    await events.events(event, request)
    assert len(store.notices) == 100 and len(store.deliveries) == 1
    assert len(catalog.calls) == 100 and peak == 10 and active == 0


@pytest.mark.asyncio
async def test_failed_batch_finishes_calls_and_rolls_back_before_retry():
    store, catalog = Store(), Catalog()
    for _ in range(11):
        await service.command(store, OWNER, command(), catalog)
    original = catalog.match
    calls = active = 0

    async def interrupted(*args):
        nonlocal calls, active
        calls += 1
        active += 1
        try:
            if calls == 11:
                raise TimeoutError()
            await asyncio.sleep(.01)
            return await original(*args)
        finally:
            active -= 1

    catalog.match = interrupted
    published = publication()
    with pytest.raises(PublicError, match='unavailable'):
        async with store.transaction():
            await service.deliver(store, OWNER, published, catalog)
    assert active == 0 and not store.notices and not store.deliveries
    catalog.match = original
    await service.deliver(store, OWNER, published, catalog)
    await service.deliver(store, OWNER, published, catalog)
    assert len(store.notices) == 11 and len(store.deliveries) == 1
