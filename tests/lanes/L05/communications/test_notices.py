import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from uuid import uuid4
import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from bt_bulkheads import DependencyClient
from bt_contracts_core.models import Actor, EventEnvelope
from bt_runtime.app.db import create_pool
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.principal import CurrentPrincipal

BUYER, OTHER, THIRD = uuid4(), uuid4(), uuid4()


@pytest.fixture
def keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode(), key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())


@pytest_asyncio.fixture
async def api(database_url, keys):
    private, public = keys
    app = create_app(Settings(database_url=database_url, service_name='communications',
        modules_path=Path('/app/modules'), service_auth_public_key=public))
    app.state.pool = await create_pool(database_url)
    def upstream(request):
        if request.url.host == 'identity':
            subject = request.headers.get('authorization', '').removeprefix('Bearer ')
            if subject not in map(str, (BUYER, OTHER, THIRD)):
                return httpx.Response(403)
            return httpx.Response(200, json=CurrentPrincipal(actor=Actor(subject_id=subject,
                session_id='sample-session'), roles=['buyer']).model_dump(mode='json'))
        return httpx.Response(200, json={'id': 'current-auction', 'current_minor': 470000,
            'next_minimum_minor': 480000, 'currency': 'USD', 'ends_at': '2026-11-05T12:00:00Z',
            'server_time': '2026-11-04T12:00:00Z', 'revision': 9, 'accepted_sequence': 8,
            'status': 'live', 'private_field_must_not_leak': 'secret'})
    app.state.bid_notice_clients = {name: DependencyClient(name, f'http://{name}',
        transport=httpx.MockTransport(upstream)) for name in ('identity', 'auction')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, app, private
    for client in app.state.bid_notice_clients.values():
        await client.aclose()
    await app.state.pool.close()


def auth(private, **overrides):
    now = int(time.time())
    return {'Authorization': 'Bearer ' + jwt.encode({'sub': 'auction', 'aud': 'communications',
        'iss': 'beirut-time-identity', 'iat': now, 'exp': now + 60, 'type': 'service', **overrides},
        private, algorithm='RS256')}


def event(**overrides):
    data = {'auction_id': str(uuid4()), 'listing_id': str(uuid4()), 'sequence': 2, 'revision': 3,
        'current_minor': 410000, 'currency': 'USD', 'ends_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        'bidder_id': str(OTHER), 'previous_leader_id': str(BUYER), 'leader_id': str(OTHER), **overrides}
    return EventEnvelope(type='auction.bid-accepted.v1', source='auction', subject=data['auction_id'],
        request_id='sample-bid-event', data=data).model_dump(mode='json')


async def test_actual_outbid_is_deduplicated_and_owner_private(api):
    client, app, private = api
    body = event()
    first = await client.post('/internal/v1/events', headers=auth(private), json=body)
    replay = await client.post('/internal/v1/events', headers=auth(private), json=body)
    assert first.json() == {'accepted': True} and replay.json() == {'accepted': False}
    buyer = (await client.get('/v1/bid-notices', headers={'Authorization': f'Bearer {BUYER}'})).json()
    other = (await client.get('/v1/bid-notices', headers={'Authorization': f'Bearer {OTHER}'})).json()
    assert [n['kind'] for n in buyer['items']] == ['outbid']
    assert [n['kind'] for n in other['items']] == ['bid_accepted']
    notice_id = buyer['items'][0]['id']
    assert (await client.get(f'/v1/bid-notices/{notice_id}', headers={'Authorization': f'Bearer {OTHER}'})).status_code == 404
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM bid_notices') == 2
        assert await tx.fetchval('SELECT count(*) FROM inbox') == 1


async def test_historical_notice_rereads_current_and_never_grants_bid(api):
    client, _, private = api
    await client.post('/internal/v1/events', headers=auth(private), json=event())
    notices = (await client.get('/v1/bid-notices', headers={'Authorization': f'Bearer {BUYER}'})).json()
    result = await client.get('/v1/bid-notices/' + notices['items'][0]['id'], headers={'Authorization': f'Bearer {BUYER}'})
    assert result.json()['current']['current_minor'] == 470000
    assert result.json()['notice']['current_minor'] == 410000
    assert result.json()['requires_new_fee_preview'] is True
    assert 'secret' not in result.text and str(OTHER) not in result.text


@pytest.mark.parametrize('claims', [{'type': 'access'}, {'aud': 'auction'}, {'sub': 'catalog'}, {'exp': 1}])
async def test_user_wrong_producer_wrong_audience_and_expired_tokens_refused(api, claims):
    client, app, private = api
    response = await client.post('/internal/v1/events', headers=auth(private, **claims), json=event())
    assert response.status_code in (401, 403)
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM bid_notices') == 0


async def test_unchanged_leader_never_emits_spurious_outbid(api):
    client, _, private = api
    body = event(leader_id=str(BUYER))
    await client.post('/internal/v1/events', headers=auth(private), json=body)
    notices = (await client.get('/v1/bid-notices', headers={'Authorization': f'Bearer {BUYER}'})).json()
    assert not notices['items']


async def test_private_maximum_field_refused_atomically(api):
    client, app, private = api
    result = await client.post('/internal/v1/events', headers=auth(private), json=event(private_maximum=450000))
    assert result.status_code == 422
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM inbox') == 0
        assert await tx.fetchval('SELECT count(*) FROM bid_notices') == 0


async def test_event_subject_must_match_the_canonical_auction(api):
    client, app, private = api
    body = event()
    body['subject'] = str(uuid4())
    result = await client.post('/internal/v1/events',headers=auth(private),json=body)
    assert result.status_code == 422
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM inbox') == 0
        assert await tx.fetchval('SELECT count(*) FROM bid_notices') == 0


async def test_unavailable_current_state_is_honest(api):
    client, app, private = api
    await client.post('/internal/v1/events', headers=auth(private), json=event())
    old = app.state.bid_notice_clients['auction']
    app.state.bid_notice_clients['auction'] = DependencyClient('auction', 'http://auction',
        transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    await old.aclose()
    notices = (await client.get('/v1/bid-notices', headers={'Authorization': f'Bearer {BUYER}'})).json()
    opened = (await client.get('/v1/bid-notices/' + notices['items'][0]['id'], headers={'Authorization': f'Bearer {BUYER}'})).json()
    assert opened['current'] is None and opened['current_status'] == 'unavailable'


async def test_inbox_bridge_retries_and_fences_delivery(api, monkeypatch):
    client, app, private = api
    module = next(m for m in app.state.modules if m.id == 'L05.bid-notices')
    run = module.load('workers.py:bridge')
    import sys
    workers = sys.modules[run.__module__]
    monkeypatch.setenv('BT_SERVICE_AUTH_PRIVATE_KEY', private)
    requests = []
    def inbox(request):
        requests.append(request)
        return httpx.Response(503 if len(requests) == 1 else 200, json={'accepted': True})
    real = DependencyClient
    monkeypatch.setattr(workers, 'DependencyClient', lambda name, url, **kwargs: real(name, url,
        **kwargs, transport=httpx.MockTransport(inbox)))
    await client.post('/internal/v1/events', headers=auth(private), json=event())
    stop = asyncio.Event()
    task = asyncio.create_task(run(app, stop))
    try:
        for _ in range(70):
            await asyncio.sleep(.05)
            async with app.state.pool.acquire() as tx:
                delivered = await tx.fetchval('SELECT count(*) FROM bid_notices WHERE delivered_at IS NOT NULL')
            if delivered == 2:
                break
        assert delivered == 2
        assert len(requests) == 3
        assert requests[0].url.path == '/internal/v1/notices'
        body = json.loads(requests[0].content)
        assert set(body) == {'id','recipient_id','kind','resource_type','resource_id',
            'href','created_at','resource_revision','data'}
        assert body['resource_type']=='auction' and body['href'].startswith('/watches/')
        assert set(body['data'])=={'current_minor','currency','ends_at','sequence'}
        assert body['resource_revision'] is None
        # Validate against the actual merged Inbox provider model, not a permissive
        # transport acknowledgement that could hide a 422 in a connected run.
        import sys
        provider=next(m for m in app.state.modules if m.id=='L07.inbox')
        bridge=provider.load('bridge.py:bridge')
        model=sys.modules[bridge.__module__].BridgeNotice
        model.model_validate(body)
        assert b'private_maximum' not in requests[0].content
        assert json.loads(requests[0].content) == json.loads(requests[-1].content)
    finally:
        stop.set()
        await task
