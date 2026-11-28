import asyncio
import json
import sys
from datetime import datetime, timedelta
from uuid import UUID, uuid4
import httpx
import asyncpg
import pytest
from bt_bulkheads import DependencyClient
from bt_runtime.app.settings import Settings
from service_app.main import create_app

ALICE, BOB = uuid4(), uuid4()
BODY = {'subject_id': str(uuid4()), 'subject_revision': 1, 'purpose': 'purchase', 'currency': 'USD', 'price_minor': 500000, 'schedule_id': 'usd-v2'}
PUBLICATION = {'id': BODY['subject_id'], 'revision': 1, 'status': 'published', 'physical_watch_id': str(uuid4()), 'seller_id': str(uuid4()),
    'facts': {'currency': 'USD', 'price_minor': 500000, 'sale_mode': 'fixed_price'}}


def identity(request):
    token = request.headers.get('Authorization', '')
    if token == 'Bearer unavailable':
        return httpx.Response(503)
    if token == 'Bearer malformed':
        return httpx.Response(200, json={'actor': 'invalid'})
    if token not in ('Bearer alice', 'Bearer bob'):
        return httpx.Response(401)
    owner = ALICE if token == 'Bearer alice' else BOB
    return httpx.Response(200, json={'actor': {'subject_id': str(owner), 'session_id': 'test'}, 'roles': ['buyer']})


@pytest.fixture
async def api(database_url):
    app = create_app(Settings(database_url=database_url, service_name='pricing'))
    async with app.router.lifespan_context(app):
        await app.state.identity.aclose()
        app.state.identity = DependencyClient('identity', 'http://identity', transport=httpx.MockTransport(identity))
        await app.state.catalog.aclose()
        app.state.catalog = DependencyClient('catalog', 'http://catalog', transport=httpx.MockTransport(lambda request: httpx.Response(200, json=PUBLICATION)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield app, client
        await app.state.identity.aclose()
        await app.state.catalog.aclose()


def headers(key='create-quote-one', token='alice'):
    return {'Authorization': 'Bearer ' + token, 'Idempotency-Key': key}


@pytest.mark.asyncio
async def test_exact_snapshot_replay_scope_and_restart(api, database_url):
    app, client = api
    first, second = await asyncio.gather(*(client.post('/v1/quotes', json=BODY, headers=headers()) for _ in range(2)))
    assert first.status_code == second.status_code == 201
    quote = first.json()
    assert quote == second.json()
    assert (quote['price_minor'], quote['buyer_fee_minor'], quote['payable_minor']) == (500000, 15000, 515000)
    assert (quote['seller_commission_minor'], quote['seller_net_minor']) == (25000, 475000)
    assert quote['sample'] and quote['fx'] is None and quote['tax_minor'] == quote['shipping_minor'] == 0
    assert (await client.post('/v1/quotes', json={**BODY, 'price_minor': 1}, headers=headers())).status_code == 409
    assert (await client.get('/v1/quotes/' + quote['id'], headers=headers(token='bob'))).status_code == 404
    assert (await client.get('/v1/quotes', headers=headers(token='unavailable'))).status_code == 503
    assert (await client.get('/v1/quotes', headers=headers(token='malformed'))).status_code == 503
    assert (await client.get('/v1/quotes')).status_code == 401
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM l07_quotes') == 1
        assert await tx.fetchval('SELECT count(*) FROM outbox') == 1
    # A new runtime process/connection observes the acknowledged immutable version.
    restored = create_app(Settings(database_url=database_url, service_name='pricing'))
    async with restored.router.lifespan_context(restored):
        async with restored.state.pool.acquire() as tx:
            row = await tx.fetchrow('SELECT * FROM l07_quotes WHERE id=$1', UUID(quote['id']))
            assert json.loads(row['snapshot'])['payable_minor'] == 515000


@pytest.mark.asyncio
@pytest.mark.parametrize('amount', [True, 500000.0, '5,000', '٥٠٠٠', '500000', -1, 0, 9000000000001])
async def test_ambiguous_float_and_unbounded_money_denied(api, amount):
    _, client = api
    assert (await client.post('/v1/quotes', json={**BODY, 'price_minor': amount}, headers=headers())).status_code == 422


@pytest.mark.asyncio
async def test_review_all_bindings_and_replay(api):
    app, client = api
    q = (await client.post('/v1/quotes', json=BODY, headers=headers())).json()
    review = {**BODY, 'quote_revision': 1, 'payable_minor': 515000}
    path = '/v1/quotes/' + q['id'] + '/review'
    for field, value in [('subject_id', str(uuid4())), ('subject_revision', 2), ('purpose', 'offer'), ('price_minor', 500001), ('quote_revision', 2), ('payable_minor', 515001)]:
        assert (await client.post(path, json={**review, field: value}, headers=headers('review-' + field))).status_code == 409
    assert (await client.post(path, json={**review, 'currency': 'LBP'}, headers=headers('review-currency'))).status_code == 422
    accepted = await client.post(path, json=review, headers=headers('review-once'))
    assert accepted.status_code == 200 and accepted.json()['reviewed_at']
    assert (await client.post(path, json=review, headers=headers('review-once'))).json() == accepted.json()
    assert (await client.post(path, json=review, headers=headers('another-review'))).status_code == 409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM l07_quote_reviews') == 1
    another = (await client.post('/v1/quotes', json=BODY, headers=headers('create-second'))).json()
    conflict = await client.post('/v1/quotes/' + another['id'] + '/review', json=review, headers=headers('review-once'))
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'idempotency_conflict'


@pytest.mark.asyncio
@pytest.mark.parametrize('offset, status', [(-1, 200), (0, 409), (1, 409)])
async def test_expiration_before_equal_after(api, monkeypatch, offset, status):
    app, client = api
    q = (await client.post('/v1/quotes', json=BODY, headers=headers())).json()
    instant = datetime.fromisoformat(q['expires_at']) + timedelta(microseconds=offset)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant
    endpoint = next(r.endpoint for r in app.routes if getattr(r, 'path', '') == '/v1/quotes/{quote_id}/review')
    monkeypatch.setattr(sys.modules[endpoint.__module__], 'datetime', Clock)
    response = await client.post('/v1/quotes/' + q['id'] + '/review', json={**BODY, 'quote_revision': 1, 'payable_minor': 515000}, headers=headers('review-boundary'))
    assert response.status_code == status
    if status == 409:
        assert response.json()['error']['code'] == 'quote_expired'


@pytest.mark.asyncio
async def test_snapshot_database_guards_prevent_rewrites_and_unbalanced_money(api):
    app, client = api
    quote = (await client.post('/v1/quotes', json=BODY, headers=headers())).json()
    async with app.state.pool.acquire() as tx:
        with pytest.raises(asyncpg.RaiseError, match='immutable'):
            await tx.execute("UPDATE l07_quotes SET snapshot=jsonb_set(snapshot,'{payable_minor}','1') WHERE id=$1", UUID(quote['id']))
        with pytest.raises(asyncpg.RaiseError, match='deleted'):
            await tx.execute('DELETE FROM l07_quotes WHERE id=$1', UUID(quote['id']))
        invalid = {**quote, 'id': str(uuid4()), 'payable_minor': 1}
        with pytest.raises(asyncpg.CheckViolationError):
            await tx.execute('INSERT INTO l07_quotes(id,owner_id,idempotency_key,request_hash,snapshot,created_at,expires_at) VALUES($1,$2,$3,$4,$5::jsonb,$6,$7)',
                UUID(invalid['id']), ALICE, 'invalid-insert', 'proof', json.dumps(invalid), datetime.fromisoformat(quote['created_at']), datetime.fromisoformat(quote['expires_at']))


@pytest.mark.asyncio
async def test_listing_bound_quote_and_exact_orders_validation(api):
    app, client = api
    assert (await client.post('/v1/quotes', json={**BODY, 'source': 'listing', 'price_minor': 1}, headers=headers('cheap-watch'))).status_code == 409
    quote = (await client.post('/v1/quotes', json={**BODY, 'source': 'listing'}, headers=headers())).json()
    assert quote['source_verified'] is True
    path = '/internal/v1/quotes/' + quote['id'] + '/validation'
    validated = await client.get(path, headers=headers())
    assert validated.status_code == 200
    assert validated.json() == {'quote_id': quote['id'], 'buyer_id': str(ALICE), 'listing_id': BODY['subject_id'],
        'listing_revision': 1, 'currency': 'USD', 'total_minor': 515000, 'expires_at': quote['expires_at'], 'status': 'valid'}
    assert (await client.get(path, headers=headers(token='bob'))).status_code == 404
    sample = (await client.post('/v1/quotes', json=BODY, headers=headers('sample-quote'))).json()
    assert (await client.get('/internal/v1/quotes/' + sample['id'] + '/validation', headers=headers())).status_code == 403
    for response, status in [(httpx.Response(200, json={**PUBLICATION, 'revision': 2}), 409), (httpx.Response(200, json={}), 503), (httpx.Response(503), 503)]:
        await app.state.catalog.aclose()
        app.state.catalog = DependencyClient('catalog', 'http://catalog', transport=httpx.MockTransport(lambda request, response=response: response))
        assert (await client.get(path, headers=headers())).status_code == status
    replay = await client.post('/v1/quotes', json={**BODY, 'source': 'listing'}, headers=headers())
    assert replay.status_code == 201 and replay.json() == quote


@pytest.mark.asyncio
@pytest.mark.parametrize('offset,status', [(-1, 200), (0, 409), (1, 409)])
async def test_reservation_quote_validation_expiry_boundary(api, monkeypatch, offset, status):
    app, client = api
    quote = (await client.post('/v1/quotes', json={**BODY, 'source': 'listing'}, headers=headers())).json()
    instant = datetime.fromisoformat(quote['expires_at']) + timedelta(microseconds=offset)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == '/internal/v1/quotes/{quote_id}/validation')
    monkeypatch.setattr(sys.modules[endpoint.__module__], 'datetime', Clock)
    assert (await client.get('/internal/v1/quotes/' + quote['id'] + '/validation', headers=headers())).status_code == status


@pytest.mark.asyncio
async def test_changed_listing_requires_new_review_not_silent_substitution(api):
    app, client = api
    quote = (await client.post('/v1/quotes', json={**BODY, 'source': 'listing'}, headers=headers())).json()
    await app.state.catalog.aclose()
    app.state.catalog = DependencyClient('catalog', 'http://catalog', transport=httpx.MockTransport(lambda request: httpx.Response(200, json={**PUBLICATION, 'revision': 2})))
    review = {**BODY, 'source': 'listing', 'quote_revision': 1, 'payable_minor': 515000}
    denied = await client.post('/v1/quotes/' + quote['id'] + '/review', json=review, headers=headers('review-current'))
    assert denied.status_code == 409 and denied.json()['error']['code'] == 'listing_changed'
    retained = (await client.get('/v1/quotes/' + quote['id'], headers=headers())).json()
    assert retained['reviewed_at'] is None and retained['payable_minor'] == 515000
