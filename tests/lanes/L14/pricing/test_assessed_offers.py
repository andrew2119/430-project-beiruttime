"""Real restricted Pricing DB; HTTP peers follow frozen contracts, not live proof."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_bulkheads import DependencyClient
from bt_runtime.app.settings import Settings
from service_app.main import create_app

BUYER, OTHER, SELLER, STAFF, ORG = (uuid4() for _ in range(5))
SOURCE, ASSESSMENT, LISTING, WATCH, REQUIRED, OPTIONAL = (uuid4() for _ in range(6))


def headers(who='buyer', key=None):
    return {'Authorization': 'Bearer ' + who, 'Idempotency-Key': key or str(uuid4())}


def identity(request):
    if request.url.path.startswith('/v1/businesses/'):
        return httpx.Response(200, json={'id': str(ORG), 'state': 'active', 'kind': 'brand',
            'platform_onboarded': True, 'authenticated_business': True, 'capabilities': ['customization', 'servicing']})
    who = request.headers.get('authorization', '').replace('Bearer ', '')
    people = {'buyer': BUYER, 'other': OTHER, 'seller': SELLER, 'staff': STAFF}
    if who not in people:
        return httpx.Response(401)
    org = str(ORG) if request.url.params.get('organization_id') == str(ORG) and who == 'staff' else None
    return httpx.Response(200, json={'actor': {'subject_id': str(people[who]), 'session_id': 'test', 'organization_id': org},
        'roles': ['brand'] if who == 'staff' else ['buyer', 'private_seller'],
        'permissions': ['identity.listings.publish'] if who == 'seller' else [],
        'organizations': [str(ORG)] if who == 'staff' else [],
        'organization_grants': [{'organization_id': str(ORG), 'permissions': ['business.jobs.write', 'business.records.read'], 'roles': ['brand']}] if who == 'staff' else []})


@pytest.fixture
async def api(database_url, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setenv('BT_SERVICE_AUTH_PRIVATE_KEY', private)
    app = create_app(Settings(database_url=database_url, service_name='pricing', service_auth_public_key=public))
    state = {'source_revision': 1, 'assessment_revision': 1, 'unavailable': False, 'remote_results': {}, 'winner': None, 'lose_reply': False}
    publication = {'id': str(LISTING), 'revision': 1, 'physical_watch_id': str(WATCH), 'seller_id': str(SELLER),
        'organization_id': None, 'status': 'published', 'facts': {'currency': 'USD', 'sale_mode': 'fixed_price', 'price_minor': 10000}}
    lines = [{'id': str(REQUIRED), 'label': 'Diagnosed seal', 'kind': 'part', 'mandatory': True, 'part_reference': 'SEAL-A'},
             {'id': str(OPTIONAL), 'label': 'Optional diagnosed test', 'kind': 'labor', 'mandatory': False, 'part_reference': None}]
    def catalog(request):
        if state['unavailable']:
            return httpx.Response(503)
        if '/customization-requests/' in request.url.path:
            return httpx.Response(200, json={'id': str(SOURCE), 'revision': state['source_revision'], 'buyer_id': str(BUYER), 'brand_id': str(ORG)})
        return httpx.Response(200, json=publication)
    def assessment(request):
        if state['unavailable']:
            return httpx.Response(503)
        brand = '/brand-assessments/' in request.url.path
        payload = {'id': str(ASSESSMENT), 'revision': state['assessment_revision'],
            'request_id': str(SOURCE), 'request_revision': state['source_revision'], 'case_id': str(SOURCE),
            'case_revision': state['source_revision'], 'buyer_id': str(BUYER), 'organization_id': str(ORG),
            'status': 'feasible' if brand else 'diagnosed', 'current': True, 'diagnosis_allowed': True,
            'line_ids': [line['id'] for line in lines], 'lines': lines, 'currency': 'USD',
            'diagnosis': 'Diagnosed worn seal; optional rate test', 'technical_summary': 'Feasible assessed technical scope'}
        return httpx.Response(200, json={**payload, **state.get('assessment_override', {})})
    def auction(request):
        if state.get('auction_unavailable'):
            return httpx.Response(503)
        if request.url.path.endswith('/prebid-basis'):
            return httpx.Response(200, json={'auction_id': str(SOURCE), 'buyer_id': request.url.params['buyer_id'],
                'quote_id': request.url.params['quote_id'], 'quote_revision': 1,
                'admission_revision': state['source_revision'], 'current_revision': state.get('basis_current', 2),
                'watch_id': str(WATCH), 'listing_id': str(LISTING), 'listing_revision': 1,
                'currency': 'USD', 'price_minor': 10000, 'total_minor': 10300,
                'mode': 'prebid_pending', 'prepared_at': datetime.now(timezone.utc).isoformat()})
        context = {'auction_id': str(SOURCE), 'listing_id': str(LISTING), 'listing_revision': 1,
            'watch_id': str(WATCH), 'buyer_id': request.url.params['buyer_id'], 'seller_id': str(SELLER),
            'seller_organization_id': None, 'revision': state['source_revision'], 'end_version': 1, 'close_version': 1,
            'mode': 'closed_winner' if request.url.params['kind'] == 'winner' else 'bidding',
            'currency': 'USD', 'price_minor': 10000, 'ends_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        return httpx.Response(200, json={**context, **state.get('auction_override', {})})
    async def orders(request):
        if '/operations/' in request.url.path:
            operation = request.url.path.rsplit('/', 1)[-1]
            return httpx.Response(200, json=state['remote_results'][operation]) if operation in state['remote_results'] else httpx.Response(404)
        if request.method == 'GET':
            return httpx.Response(200, json={'watch_id': str(WATCH), 'listing_id': str(LISTING), 'listing_revision': 1,
                'revision': 1, 'status': 'available' if state['winner'] is None else 'reserved'})
        body = json.loads(request.content)
        operation = body['operation_key']
        if operation not in state['remote_results']:
            # This fake is the frozen Orders fence fixture, never a payment fixture.
            succeeded = state['winner'] is None
            if succeeded:
                state['winner'] = operation
                order_id = str(uuid4())
                order = {field: body[field] for field in
                         ('watch_id', 'listing_id', 'buyer_id', 'quote_id', 'quote_revision', 'currency', 'total_minor')}
                state['remote_results'][operation] = {
                    'id': str(uuid4()), 'request_id': 'orders-fence-test', 'status': 'succeeded',
                    'resource_id': order_id, 'order': {'id': order_id, **order},
                }
            else:
                state['remote_results'][operation] = {'id': str(uuid4()), 'status': 'denied', 'order': None}
        if state['lose_reply']:
            state['lose_reply'] = False
            return httpx.Response(503)
        return httpx.Response(200, json=state['remote_results'][operation])
    async with app.router.lifespan_context(app):
        clients = {}
        for name, handler in [('identity', identity), ('catalog', catalog), ('service_operations', assessment), ('orders', orders), ('auction', auction)]:
            await getattr(app.state, name).aclose()
            client = DependencyClient(name, 'http://' + name, transport=httpx.MockTransport(handler))
            setattr(app.state, name, client)
            clients[name] = client
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield app, client, state, private, lines
        for client in clients.values():
            await client.aclose()


def issue_body(lines, kind='repair'):
    quoted = [dict(line, amount_minor=10000 if line['id'] == str(REQUIRED) else 5000,
                   mandatory=True if kind == 'brand' else line['mandatory']) for line in lines]
    return {'source_id': str(SOURCE), 'source_revision': 1, 'assessment_id': str(ASSESSMENT), 'assessment_revision': 1,
        'currency': 'USD', 'lines': quoted, 'assessment_fee_minor': 1000, 'return_fee_minor': 2000,
        'warranty_terms': 'Seal only, 90 days', 'modification_terms': 'No polishing or unassessed parts',
        'indicative_min_minor': 10000, 'indicative_max_minor': 20000, 'indicative_basis': 'Current diagnosed parts and labor',
        'lead_time_days': 4, 'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(), 'schedule_id': 'usd-job-v2'}


async def issue(api):
    app, client, state, private, lines = api
    response = await client.post('/v1/repair-quotes?organization_id=' + str(ORG), json=issue_body(lines), headers=headers('staff'))
    assert response.status_code == 201, response.text
    return response.json()['quote']


def accept_body(q, selected=None):
    selected = selected or [str(REQUIRED)]
    base = 11000 + (5000 if str(OPTIONAL) in selected else 0)
    return {'quote_revision': q['revision'], 'selected_line_ids': selected,
            'payable_minor': base, 'terms_digest': q['terms_digest'], 'accept_assessment_fee': True, 'accept_return_fee': False}


@pytest.mark.asyncio
async def test_repair_exact_selected_scope_attribution_replay_and_outbox(api):
    app, client, state, _, _ = api
    q = await issue(api)
    path = '/v1/repair-quotes/' + q['id'] + '/accept'
    body, h = accept_body(q), headers(key='repair-accept-once')
    first, second = await asyncio.gather(*(client.post(path, json=body, headers=h) for _ in range(2)))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    decision = first.json()['quote']['decision']
    assert decision['actor_id'] == str(BUYER)
    assert decision['selected_line_ids'] == [str(REQUIRED)]
    assert decision['amounts']['payable_minor'] == 11000
    assert (await client.post(path, json={**body, 'payable_minor': 1}, headers=h)).status_code == 409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM l14_quote_decisions') == 1
        rows = await tx.fetch("SELECT envelope FROM outbox WHERE destination='accepted-quotes-v1'")
        assert len(rows) == 2
        assert all('Seal only' not in row['envelope'] and 'No polishing' not in row['envelope'] for row in rows)


@pytest.mark.asyncio
async def test_optional_line_exact_total_mandatory_denial_and_wrong_actor(api):
    _, client, _, _, _ = api
    q = await issue(api)
    path = '/v1/repair-quotes/' + q['id'] + '/accept'
    assert (await client.post(path, json=accept_body(q), headers=headers('other'))).status_code == 403
    assert (await client.post(path + '?organization_id=' + str(ORG), json=accept_body(q), headers=headers('staff'))).status_code == 403
    missing = accept_body(q, [str(OPTIONAL)])
    assert (await client.post(path, json=missing, headers=headers())).status_code == 409
    body = accept_body(q, [str(REQUIRED), str(OPTIONAL)])
    assert (await client.post(path, json={**body, 'terms_digest': '0' * 64}, headers=headers())).status_code == 409
    accepted = await client.post(path, json=body, headers=headers())
    assert accepted.status_code == 200 and accepted.json()['quote']['decision']['amounts']['payable_minor'] == 16000


@pytest.mark.asyncio
async def test_assessment_revision_unavailable_and_supersession_require_reacceptance(api):
    _, client, state, _, lines = api
    q = await issue(api)
    state['assessment_revision'] = 2
    assert (await client.post('/v1/repair-quotes/' + q['id'] + '/accept', json=accept_body(q), headers=headers())).status_code == 409
    state['assessment_revision'] = 1
    state['unavailable'] = True
    assert (await client.post('/v1/repair-quotes/' + q['id'] + '/accept', json=accept_body(q), headers=headers())).status_code == 503
    state['unavailable'] = False
    replacement = issue_body(lines)
    replacement['lines'][0]['amount_minor'] += 100
    newer = await client.post('/v1/repair-quotes?organization_id=' + str(ORG), json=replacement, headers=headers('staff'))
    assert newer.status_code == 201 and newer.json()['quote']['revision'] == 2
    assert (await client.post('/v1/repair-quotes/' + q['id'] + '/accept', json=accept_body(q), headers=headers())).status_code == 409
    retained = (await client.get('/v1/repair-quotes/' + q['id'], headers=headers())).json()
    assert retained['state'] == 'superseded' and retained['full_total']['payable_minor'] == 16000


@pytest.mark.asyncio
async def test_decline_is_held_return_no_work_and_private_read(api):
    app, client, _, _, _ = api
    q = await issue(api)
    declined = await client.post('/v1/repair-quotes/' + q['id'] + '/decline',
        json={'quote_revision': q['revision'], 'terms_digest': q['terms_digest']}, headers=headers())
    assert declined.status_code == 200 and declined.json()['quote']['state'] == 'declined_return_held'
    assert declined.json()['quote']['decision']['selected_line_ids'] == []
    assert (await client.get('/v1/repair-quotes/' + q['id'], headers=headers('other'))).status_code == 403
    assert (await client.get('/v1/repair-quotes/' + q['id'])).status_code == 401
    async with app.state.pool.acquire() as tx:
        assert not await tx.fetchval("SELECT EXISTS(SELECT 1 FROM l14_quote_decisions WHERE decision='accepted')")


async def offer_command(client, who='buyer', *, reviewed=True):
    body = {'subject_id': str(LISTING), 'subject_revision': 1, 'purpose': 'offer', 'currency': 'USD', 'price_minor': 10000,
            'schedule_id': 'usd-v2', 'source': 'sample'}
    q = (await client.post('/v1/quotes', json=body, headers=headers(who))).json()
    if reviewed:
        review = await client.post('/v1/quotes/' + q['id'] + '/review', json={**body, 'quote_revision': 1, 'payable_minor': 10300}, headers=headers(who))
        assert review.status_code == 200
    return {'listing_id': str(LISTING), 'listing_revision': 1, 'amount_minor': 10000,
        'currency': 'USD', 'schedule_id': 'usd-v2', 'fee_quote_id': q['id']}


async def make_offer(client, who='buyer'):
    response = await client.post('/v1/offers', json=await offer_command(client, who), headers=headers(who))
    assert response.status_code == 201, response.text
    return response.json()['offer']


@pytest.mark.asyncio
async def test_offer_lost_response_persists_pending_reconciles_same_order_closes_competitors(api):
    app, client, state, _, _ = api
    first = await make_offer(client)
    competing = await make_offer(client, 'other')
    state['lose_reply'] = True
    path = '/v1/offers/' + first['id'] + '/answer'
    body, h = {'expected_revision': 1, 'action': 'accept'}, headers('seller', 'offer-accept-once')
    pending = await client.post(path, json=body, headers=h)
    assert pending.status_code == 200 and pending.json()['status'] == 'pending'
    assert pending.json()['offer']['state'] == 'acceptance_pending'
    restored = await client.post(path, json=body, headers=h)
    assert restored.status_code == 200 and restored.json()['status'] == 'succeeded'
    assert restored.json()['offer']['order_id']
    assert len(state['remote_results']) == 1
    closed = await client.get('/v1/offers/' + competing['id'], headers=headers('other'))
    assert closed.json()['state'] == 'closed'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l14_offers WHERE state='accepted'") == 1
    assert (await client.post(path, json=body, headers=h)).json() == restored.json()


@pytest.mark.asyncio
async def test_two_offer_accepts_share_one_orders_fence_and_wrong_party_denies(api):
    _, client, state, _, _ = api
    a, b = await make_offer(client), await make_offer(client, 'other')
    assert (await client.post('/v1/offers/' + a['id'] + '/answer', json={'expected_revision': 1, 'action': 'accept'}, headers=headers())).status_code == 403
    results = await asyncio.gather(*(client.post('/v1/offers/' + offer['id'] + '/answer', json={'expected_revision': 1, 'action': 'accept'}, headers=headers('seller')) for offer in [a, b]))
    winners = [r for r in results if r.status_code == 200 and r.json()['status'] == 'succeeded']
    assert len(winners) == 1
    assert len([v for v in state['remote_results'].values() if v['status'] == 'succeeded']) == 1


@pytest.mark.asyncio
async def test_blocked_offer_and_stale_revision_denied(api):
    _, client, _, _, _ = api
    offer = await make_offer(client)
    assert (await client.post('/v1/offers/' + offer['id'] + '/answer', json={'expected_revision': 2, 'action': 'accept'}, headers=headers('seller'))).status_code == 409
    assert (await client.post('/v1/offers/' + offer['id'] + '/block', json={}, headers=headers('seller'))).status_code == 200
    assert (await client.post('/v1/offers/' + offer['id'] + '/answer', json={'expected_revision': 1, 'action': 'accept'}, headers=headers('seller'))).status_code == 409


@pytest.mark.asyncio
async def test_service_validation_exact_buyer_and_current_acceptance(api):
    _, client, state, private, _ = api
    q = await issue(api)
    now = int(time.time())
    token = jwt.encode({'sub': 'eligibility', 'type': 'service', 'iss': 'beirut-time-identity', 'aud': 'pricing', 'iat': now, 'exp': now + 60}, private, algorithm='RS256')
    h = {'Authorization': 'Bearer ' + token}
    path = f"/internal/v3/quotes/{q['id']}/validation?buyer_id={BUYER}"
    assert (await client.get(path, headers=h)).status_code == 409
    assert (await client.post('/v1/repair-quotes/' + q['id'] + '/accept', json=accept_body(q), headers=headers())).status_code == 200
    validated = await client.get(path, headers=h)
    assert validated.status_code == 200, validated.text
    result = validated.json()
    assert result['selected_line_ids'] == [str(REQUIRED)] and result['total_minor'] == 11000
    assert result['buyer_id'] == str(BUYER) and result['assessment_revision'] == 1
    assert (await client.get(path.replace(str(BUYER), str(OTHER)), headers=h)).status_code == 403
    state['source_revision'] = 2
    assert (await client.get(path, headers=h)).status_code == 409


@pytest.mark.asyncio
async def test_brand_quote_is_attributable_current_complete_scope(api):
    _, client, state, _, lines = api
    for line in lines:
        line['mandatory'] = True
    body = issue_body(lines, 'brand')
    response = await client.post('/v1/brand-quotes?organization_id=' + str(ORG), json=body, headers=headers('staff'))
    assert response.status_code == 201, response.text
    q = response.json()['quote']
    accepted = await client.post('/v1/brand-quotes/' + q['id'] + '/accept',
        json=accept_body(q, [str(REQUIRED), str(OPTIONAL)]), headers=headers())
    assert accepted.status_code == 200 and accepted.json()['quote']['decision']['actor_id'] == str(BUYER)
    state['source_revision'] = 2
    stale = await client.post('/v1/brand-quotes?organization_id=' + str(ORG), json=body, headers=headers('staff'))
    assert stale.status_code == 409


@pytest.mark.parametrize('delta,denied', [(-1, False), (0, True), (1, True)])
def test_expiry_before_equal_after(delta, denied):
    from service_app.current import current_time
    from bt_contracts_core.errors import PublicError
    deadline = datetime(2026, 11, 5, tzinfo=timezone.utc)
    now = deadline + timedelta(microseconds=delta)
    if denied:
        with pytest.raises(PublicError):
            current_time({'expires_at': deadline}, now)
    else:
        current_time({'expires_at': deadline}, now)


@pytest.mark.asyncio
async def test_auction_purchase_is_refused_and_winner_quote_is_service_scoped(api):
    _, client, state, private, _ = api
    preview = await client.post('/v1/auction-quotes', json={'auction_id': str(SOURCE), 'expected_revision': 1}, headers=headers())
    assert preview.status_code == 409 and preview.json()['error']['code'] == 'auction_purchase_disabled'
    now = int(time.time())
    token = {'Authorization': 'Bearer ' + jwt.encode({'sub': 'auction', 'type': 'service', 'iss': 'beirut-time-identity',
        'aud': 'pricing', 'iat': now, 'exp': now + 60}, private, algorithm='RS256')}
    body = {'auction_id': str(SOURCE), 'expected_revision': 1, 'buyer_id': str(BUYER), 'operation_key': 'winner-quote-once'}
    h = {**token, 'Idempotency-Key': body['operation_key']}
    winner = await client.post('/internal/v2/auction-quotes', json=body, headers=h)
    assert winner.status_code == 201 and winner.json()['quote']['kind'] == 'winner'
    assert winner.json()['quote']['expires_at'] is None
    assert (await client.post('/internal/v2/auction-quotes', json=body, headers=h)).json() == winner.json()
    assert (await client.post('/internal/v2/auction-quotes', json=body, headers=headers())).status_code in (401, 403)


@pytest.mark.asyncio
async def test_leased_worker_reconciles_durable_pending_without_a_browser(api):
    import importlib
    app, client, state, _, _ = api
    offer = await make_offer(client)
    state['lose_reply'] = True
    pending = await client.post('/v1/offers/' + offer['id'] + '/answer', json={'expected_revision': 1, 'action': 'accept'}, headers=headers('seller'))
    assert pending.status_code == 200 and pending.json()['status'] == 'pending'
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == '/v1/offers/{offer_id}/answer')
    module = importlib.import_module(endpoint.__module__.rsplit('.', 1)[0] + '.workers')
    assert await module.tick(app) == 1
    restored = await client.get('/v1/offers/' + offer['id'], headers=headers())
    assert restored.json()['state'] == 'accepted' and restored.json()['order_id']
    assert len(state['remote_results']) == 1


@pytest.mark.asyncio
async def test_retained_economics_balance_without_becoming_current_authority(api):
    _, client, state, private, _ = api
    q = await issue(api)
    assert (await client.post('/v1/repair-quotes/' + q['id'] + '/accept', json=accept_body(q), headers=headers())).status_code == 200
    now = int(time.time())
    token = jwt.encode({'sub': 'orders', 'type': 'service', 'iss': 'beirut-time-identity', 'aud': 'pricing',
        'iat': now, 'exp': now + 60}, private, algorithm='RS256')
    h = {'Authorization': 'Bearer ' + token}
    path = f"/internal/v3/quotes/{q['id']}/retained?buyer_id={BUYER}"
    retained = await client.get(path, headers=h)
    assert retained.status_code == 200, retained.text
    money = retained.json()
    assert money['price_minor'] + money['buyer_fee_minor'] == money['payable_minor'] == 11000
    assert money['seller_net_minor'] + money['seller_commission_minor'] == money['price_minor']
    assert money['authority'] == 'retained_read_only' and 'diagnosis' not in money and 'warranty_terms' not in money
    state['unavailable'] = True
    assert (await client.get(path, headers=h)).status_code == 200
    assert (await client.get(path.replace('/retained?', '/validation?'), headers=h)).status_code == 503
    assert (await client.get(path.replace(str(BUYER), str(OTHER)), headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_self_expired_unreviewed_and_sold_offers_are_refused(api):
    _, client, state, _, _ = api
    assert (await client.post('/v1/offers', json=await offer_command(client, 'seller'), headers=headers('seller'))).status_code == 409
    command = await offer_command(client)
    expired = {**command, 'expires_at': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    assert (await client.post('/v1/offers', json=expired, headers=headers())).status_code == 422
    assert (await client.post('/v1/offers', json=await offer_command(client, reviewed=False), headers=headers())).status_code == 409
    state['winner'] = 'other-physical-reservation'
    assert (await client.post('/v1/offers', json=command, headers=headers())).status_code == 409


@pytest.mark.asyncio
async def test_buy_now_wins_offer_acceptance_without_any_losing_charge(api):
    _, client, state, _, _ = api
    offer = await make_offer(client)
    state['winner'] = 'fixed-buy-now-operation'
    response = await client.post('/v1/offers/' + offer['id'] + '/answer', json={'expected_revision': 1, 'action': 'accept'}, headers=headers('seller'))
    assert response.status_code == 200 and response.json()['status'] == 'denied'
    assert response.json()['offer']['state'] == 'lost' and response.json()['offer']['order_id'] is None
    assert not any(result['status'] == 'succeeded' for result in state['remote_results'].values())


@pytest.mark.asyncio
async def test_malformed_winner_source_never_becomes_authoritative_economics(api):
    app, client, state, private, _ = api
    now = int(time.time())
    token = {'Authorization': 'Bearer ' + jwt.encode({'sub': 'auction', 'type': 'service', 'iss': 'beirut-time-identity',
        'aud': 'pricing', 'iat': now, 'exp': now + 60}, private, algorithm='RS256')}
    body = {'auction_id': str(SOURCE), 'expected_revision': 1, 'buyer_id': str(BUYER), 'operation_key': 'malformed-winner'}
    for override in [{'revision': True}, {'price_minor': '10000'}, {'ends_at': '2026-11-05T00:00:00'},
                     {'seller_id': 'unbound'}, {'listing_revision': False}]:
        state['auction_override'] = override
        response = await client.post('/internal/v2/auction-quotes', json=body,
            headers={**token, 'Idempotency-Key': body['operation_key']})
        assert response.status_code == 503, (override, response.text)
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM l14_auction_quotes') == 0


@pytest.mark.asyncio
async def test_malformed_provider_scope_fails_closed_before_retaining_quote(api):
    app, client, state, _, lines = api
    path = '/v1/repair-quotes?organization_id=' + str(ORG)
    for override in [{'lines': [{**lines[0], 'label': ''}, lines[1]]},
                     {'lines': [lines[0], lines[0]]}, {'line_ids': [str(REQUIRED)]},
                     {'currency': 'XXX'}, {'lines': []}, {'diagnosis': None}]:
        state['assessment_override'] = override
        response = await client.post(path, json=issue_body(lines), headers=headers('staff'))
        assert response.status_code == 503, (override, response.text)
    state['assessment_override'] = {'buyer_id': str(OTHER)}
    # Brand binds both the submitted request buyer and the assessment buyer.
    body = issue_body(lines, 'brand')
    response = await client.post('/v1/brand-quotes?organization_id=' + str(ORG), json=body, headers=headers('staff'))
    assert response.status_code == 409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM l14_assessed_quotes') == 0


@pytest.mark.asyncio
async def test_close_command_adapter_reproves_all_bindings_and_replays_retained_result(api):
    app, client, state, private, _ = api
    now = int(time.time())
    def token(subject):
        return {'Authorization': 'Bearer ' + jwt.encode({'sub': subject, 'type': 'service', 'iss': 'beirut-time-identity',
            'aud': 'pricing', 'iat': now, 'exp': now + 60}, private, algorithm='RS256')}
    body = {'auction_id': str(SOURCE), 'source_id': str(SOURCE), 'watch_id': str(WATCH), 'listing_id': str(LISTING),
        'buyer_id': str(BUYER), 'seller_id': str(SELLER), 'organization_id': None,
        'currency': 'USD', 'price_minor': 10000, 'end_version': 1, 'close_version': 1, 'kind': 'winner'}
    h = {**token('auction'), 'Idempotency-Key': 'close:' + str(SOURCE)}
    path = '/internal/v2/auction-winner-quotes'
    assert (await client.post(path, json=body, headers={**h, 'Idempotency-Key': 'another-key'})).status_code == 422
    assert (await client.post(path, json=body, headers={**h, **token('orders')})).status_code == 403
    for field, value in [('price_minor', 1), ('currency', 'LBP'), ('end_version', 2), ('close_version', 2),
                         ('source_id', str(uuid4())), ('listing_id', str(uuid4())), ('watch_id', str(uuid4())),
                         ('seller_id', str(uuid4())), ('organization_id', str(uuid4()))]:
        changed = await client.post(path, json={**body, field: value}, headers=h)
        assert changed.status_code == (422 if field == 'currency' else 409), (field, changed.text)
    success = await client.post(path, json=body, headers=h)
    assert success.status_code == 201, success.text
    q = success.json()
    assert q['price_minor'] == 10000 and q['total_minor'] == 10300 and q['source_id'] == str(SOURCE)
    state['auction_unavailable'] = True
    assert (await client.post(path, json=body, headers=h)).json() == q
    assert (await client.post(path, json={**body, 'price_minor': 2}, headers=h)).status_code == 409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM l14_auction_quotes') == 1
    retained = await client.get(f"/internal/v3/quotes/{q['quote_id']}/retained?buyer_id={BUYER}", headers=token('orders'))
    assert retained.status_code == 200 and retained.json()['payable_minor'] == q['total_minor']
    assert (await client.get(f"/internal/v3/quotes/{q['quote_id']}/validation?buyer_id={BUYER}", headers=token('orders'))).status_code == 503
