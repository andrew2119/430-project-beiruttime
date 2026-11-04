import asyncio
import json
from pathlib import Path
from bt_contracts.pricing.quotes import models as quote_models
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_bulkheads import DependencyClient
from bt_runtime.app.settings import Settings
from service_app.main import create_app

ALICE, BOB = uuid4(), uuid4()
DRAFT = {'subject_id': str(uuid4()), 'subject_revision': 1, 'currency': 'USD', 'amount_minor': 480000}
EVENTS = '/internal/v1/inbox/events'


def principal(request):
    bearer = request.headers.get('Authorization', '')
    if bearer not in ('Bearer alice', 'Bearer bob'):
        return httpx.Response(401)
    return httpx.Response(200, json={'actor': {'subject_id': str(ALICE if bearer == 'Bearer alice' else BOB), 'session_id': 'test'}, 'roles': ['buyer']})


def headers(key='operation-one', token='alice'):
    return {'Authorization': 'Bearer ' + token, 'Idempotency-Key': key}


@pytest.fixture
async def api(database_url):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    settings = Settings(database_url=database_url, service_name='communications', service_auth_public_key=public)
    app = create_app(settings)
    def service_token(source='pricing', **patch):
        return jwt.encode({'sub': source, 'iss': settings.auth_issuer, 'aud': 'communications', 'iat': int(time.time()), 'exp': int(time.time()) + 60, 'type': 'service', **patch}, key, algorithm='RS256')
    async with app.router.lifespan_context(app):
        await app.state.identity.aclose()
        app.state.identity = DependencyClient('identity', 'http://identity', transport=httpx.MockTransport(principal))
        for dependency in ('orders', 'pricing'):
            await getattr(app.state, dependency).aclose()
            setattr(app.state, dependency, DependencyClient(dependency, 'http://upstream', transport=httpx.MockTransport(lambda request: httpx.Response(503))))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield app, client, service_token
        for dependency in ('identity', 'orders', 'pricing'):
            await getattr(app.state, dependency).aclose()


def event(kind='quote_ready', **patch):
    source, event_type = {'quote_ready': ('pricing', 'pricing.quote-created.v1'), 'outbid': ('auction', 'auction.outbid.v1'), 'payment_required': ('orders', 'orders.payment-required.v1')}[kind]
    now = datetime.now(timezone.utc).isoformat()
    return {'id': str(uuid4()), 'type': event_type, 'source': source, 'subject': 'synthetic-notice', 'time': now, 'request_id': 'proof', 'data': {
        'occurrence_id': str(uuid4()), 'recipient_id': str(ALICE), 'kind': kind, 'resource_id': str(uuid4()), 'resource_revision': 1,
        'resource_owner_id': str(ALICE), 'event_time': now, 'sample': True, **patch}}


@pytest.mark.asyncio
async def test_authenticated_dedupe_scope_and_canonical_markers(api):
    app, client, token = api
    payload = event()
    assert (await client.post(EVENTS, json=payload)).status_code == 401
    assert (await client.post(EVENTS, json=payload, headers={'Authorization': 'Bearer ' + token(type='access')})).status_code == 403
    assert (await client.post(EVENTS, json=event('outbid'), headers={'Authorization': 'Bearer ' + token('auction')})).status_code == 403
    service_headers = {'Authorization': 'Bearer ' + token()}
    for _ in range(2):
        assert (await client.post(EVENTS, json=payload, headers=service_headers)).status_code == 200
    # A new envelope for the same historical occurrence is also deduplicated.
    assert (await client.post(EVENTS, json={**payload, 'id': str(uuid4())}, headers=service_headers)).status_code == 200
    inbox = (await client.get('/v1/inbox', headers=headers())).json()
    assert len(inbox['items']) == inbox['unread_count'] == 1
    notice = inbox['items'][0]
    assert (await client.get('/v1/inbox', headers=headers(token='bob'))).json()['items'] == []
    path = '/v1/inbox/' + notice['id']
    assert (await client.post(path + '/read', json={'expected_revision': 1}, headers=headers(token='bob'))).status_code == 404
    first = await client.post(path + '/read', json={'expected_revision': 1}, headers=headers())
    assert first.status_code == 200 and first.json()['read_at']
    assert (await client.post(path + '/read', json={'expected_revision': 1}, headers=headers())).json() == first.json()
    assert (await client.post(path + '/clear', json={'expected_revision': 1}, headers=headers('clear-stale'))).status_code == 409
    assert (await client.post(path + '/clear', json={'expected_revision': 2}, headers=headers('clear-current'))).status_code == 200
    assert (await client.get('/v1/inbox', headers=headers())).json()['items'] == []
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM l07_notices') == 1
        assert await tx.fetchval('SELECT count(*) FROM l07_notice_operations') == 2
        assert await tx.fetchval('SELECT count(*) FROM outbox') == 2


@pytest.mark.asyncio
async def test_required_preferences_foreign_links_and_cursor_scope(api):
    _, client, token = api
    assert (await client.put('/v1/inbox/preferences', json={'optional_enabled': False, 'expected_revision': 0}, headers=headers())).status_code == 200
    for kind in ('quote_ready', 'payment_required'):
        payload = event(kind, resource_owner_id=str(BOB), required=False)
        assert (await client.post(EVENTS, json=payload, headers={'Authorization': 'Bearer ' + token(payload['source'])})).status_code == 200
    inbox = (await client.get('/v1/inbox', headers=headers())).json()
    assert len(inbox['items']) == 1 and all(notice['required'] is True for notice in inbox['items'])
    notice = inbox['items'][0]
    assert notice['destination'] is None
    assert (await client.get('/v1/inbox/' + notice['id'] + '/destination', headers=headers())).status_code == 403
    assert (await client.get('/v1/inbox?cursor=' + notice['id'], headers=headers(token='bob'))).status_code == 400






@pytest.mark.asyncio
async def test_invalid_authenticated_event_rolls_back_receipt_and_domain_work(api):
    app, client, token = api
    payload = event()
    payload['data']['kind'] = 'outbid'
    service_headers = {'Authorization': 'Bearer ' + token()}
    denied = await client.post(EVENTS, json=payload, headers=service_headers)
    assert denied.status_code == 422
    payload['data']['kind'] = 'quote_ready'
    payload['data']['resource_revision'] = -1
    assert (await client.post(EVENTS, json=payload, headers=service_headers)).status_code == 422
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM inbox') == 0
        assert await tx.fetchval('SELECT count(*) FROM l07_notices') == 0


@pytest.mark.asyncio
async def test_reordered_notices_page_canonically_without_marking_read(api):
    _, client, token = api
    for timestamp in ('2026-11-04T08:00:00Z', '2026-11-04T06:00:00Z', '2026-11-04T07:00:00Z'):
        payload = event(event_time=timestamp)
        assert (await client.post(EVENTS, json=payload, headers={'Authorization': 'Bearer ' + token()})).status_code == 200
    first = (await client.get('/v1/inbox?limit=2', headers=headers())).json()
    second = (await client.get('/v1/inbox?limit=2&cursor=' + first['next_cursor'], headers=headers())).json()
    assert first['unread_count'] == second['unread_count'] == 3
    items = first['items'] + second['items']
    assert len({item['id'] for item in items}) == 3
    assert [item['event_time'] for item in items] == sorted((item['event_time'] for item in items), reverse=True)
    assert all(item['read_at'] is None for item in items)




@pytest.mark.asyncio
async def test_l05_bridge_authenticated_durable_dedupe_and_canonical_destination(api):
    app, client, token = api
    auction_id, listing_id = uuid4(), uuid4()
    assert (await client.put('/v1/inbox/preferences', json={'optional_enabled': False, 'expected_revision': 0}, headers=headers())).status_code == 200
    now = datetime.now(timezone.utc).isoformat()
    payload = {'id': str(uuid4()), 'recipient_id': str(ALICE), 'kind': 'outbid', 'resource_type': 'auction',
        'resource_id': str(auction_id), 'href': '/watches/' + str(listing_id), 'created_at': now,
        'data': {'current_minor': 501000, 'currency': 'USD', 'ends_at': now, 'sequence': 2}}
    path = '/internal/v1/notices'
    assert (await client.post(path, json=payload, headers=headers())).status_code == 401
    assert (await client.post(path, json=payload, headers={'Authorization': 'Bearer ' + token()})).status_code == 403
    service_headers = {'Authorization': 'Bearer ' + token('communications')}
    assert (await client.post(path, json={**payload, 'data': {**payload['data'], 'private_maximum': 900000}}, headers=service_headers)).status_code == 422
    assert (await client.post(path, json=payload, headers=service_headers)).json() == {'accepted': True}
    assert (await client.post(path, json=payload, headers=service_headers)).json() == {'accepted': False}
    inbox = (await client.get('/v1/inbox', headers=headers())).json()
    assert len(inbox['items']) == 1 and inbox['items'][0]['required']
    assert inbox['items'][0]['resource_revision'] is None
    await app.state.auction.aclose()
    app.state.auction = DependencyClient('auction', 'http://auction', transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'listing_id': str(listing_id)})))
    destination = (await client.get('/v1/inbox/' + inbox['items'][0]['id'] + '/destination', headers=headers())).json()
    assert destination['url'] == '/watches/' + str(listing_id)
    await app.state.auction.aclose()


