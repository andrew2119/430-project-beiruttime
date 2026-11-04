import sys
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import httpx
import pytest
from fastapi import FastAPI
from bt_bulkheads import DependencyClient
from bt_contracts_core.errors import AccessDenied
from bt_runtime.app.auth import require_principal
from bt_runtime.modules import discover
from bt_runtime.principal import CurrentPrincipal

ROOT = next((p for p in Path(__file__).resolve().parents if (p / 'services').is_dir()), Path('/app'))
MODULES = ROOT / 'services/communications/modules'
if not MODULES.exists():
    MODULES = Path('/app/modules')
module = next(m for m in discover(MODULES) if m.id == 'L06.buyer-workspace')
compose = module.load('composition.py:compose')
routes_module = module.load('routes.py:workspace').__module__
routes = sys.modules[routes_module]
OWNER = '00000000-0000-0000-0000-000000000006'
OTHER = '00000000-0000-0000-0000-000000000007'
RESOURCE = '00000000-0000-0000-0000-000000000008'


def bid(**changes):
    record = dict(id=RESOURCE, auction_id=RESOURCE, listing_id=RESOURCE, buyer_id=OWNER,
                  currency='USD', opening_minor=10000, current_minor=16000, current_price_minor=16000,
                  next_minimum_minor=17000, increment_bands=[{'from_minor': 0, 'step_minor': 1000}],
                  starts_at='2030-01-01T10:00:00Z', ends_at='2030-01-01T12:00:00Z',
                  server_time='2030-01-01T11:00:00Z', revision=2, accepted_sequence=2,
                  rules_version='ordinary.v1', extension_policy='none.v1', high_value_minor=1000000,
                  reserve_set=False, leader='Bidder masked', status='live', my_status='leading', next_action='review_bid')
    return {**record, **changes}


def reservation():
    return dict(reservation_id=RESOURCE, listing_id=RESOURCE, buyer_id=OWNER,
                state='awaiting_payment', total_minor=24000, currency='USD',
                revision=1, expires_at='2030-01-01T12:00:00Z', is_demo=True)


def client(name, body=None, status=200, callback=None):
    def handler(request):
        assert request.headers['authorization'] == 'Bearer private-token'
        assert request.headers['x-request-id'] == 'request-6'
        if callback:
            callback(request)
        return httpx.Response(status, json=body)
    return DependencyClient(name, 'http://' + name, timeout=.1, concurrency=1,
                            transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_real_source_composition_never_invents_payment_or_cap():
    auction = client('auction', {'items': [bid()], 'next_cursor': None}, callback=lambda r: assert_path(r, '/v1/my-bids'))
    orders = client('orders', {'items': [reservation()], 'next_cursor': None})
    try:
        result = await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
        assert result['bids']['items'][0]['status'] == 'leading'
        assert 'is_demo' not in result['bids']['items'][0]
        assert 'leader' not in result['bids']['items'][0]
        assert result['reservations']['items'][0]['state'] == 'awaiting_payment'
        assert result['reservations']['items'][0]['payment_available'] is False
        assert result['final_results_available'] is False
        serialized = json.dumps(result)
        assert 'buyer_id' not in serialized and 'maximum' not in serialized and 'private-token' not in serialized
    finally:
        await auction.aclose()
        await orders.aclose()


def assert_path(request, path):
    assert request.url.path == path


@pytest.mark.asyncio
async def test_exact_published_auction_my_bids_wire_fixture():
    payload = json.loads((Path(__file__).parent / 'fixtures/my-bids.v1.json').read_text())
    owner = UUID(payload['items'][0]['buyer_id'])
    auction = client('auction', payload)
    orders = client('orders', {'items': [], 'next_cursor': None})
    try:
        result = await compose(owner, 'private-token', 'request-6', auction, orders)
        summary = result['bids']['items'][0]
        assert summary['status'] == 'outbid' and summary['current_price_minor'] == 410000
        assert summary['auction_id'] == payload['items'][0]['auction_id']
        assert 'is_demo' not in summary and 'buyer_id' not in summary
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('my_status', ['leading', 'outbid'])
async def test_my_status_not_auction_lifecycle_drives_buyer_label(my_status):
    auction = client('auction', {'items': [bid(my_status=my_status)], 'next_cursor': None})
    orders = client('orders', {'items': [], 'next_cursor': None})
    try:
        result = await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
        assert result['bids']['items'][0]['status'] == my_status
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
async def test_ended_participation_never_becomes_active_or_a_fabricated_winner():
    auction = client('auction', {'items': [bid(status='ended', next_action='auction_ended')], 'next_cursor': None})
    orders = client('orders', {'items': [], 'next_cursor': None})
    try:
        result = await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
        assert result['bids']['state'] == 'available' and result['bids']['items'] == []
        assert result['final_results_available'] is False
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    {'items': [{**bid(), 'buyer_id': OTHER}], 'next_cursor': None},
    {'items': [{**bid(), 'private_maximum_minor': 20000}], 'next_cursor': None},
    {'items': [{**bid(), 'current_price_minor': 1.5}], 'next_cursor': None},
    {'items': [{**bid(), 'status': 'won'}], 'next_cursor': None},
    {'items': [{**bid(), 'ends_at': '2030-01-01'}], 'next_cursor': None},
    {'items': [bid()] * 101, 'next_cursor': None},
    {'items': [{**bid(), 'id': OTHER}], 'next_cursor': None},
    {'items': [{**bid(), 'current_minor': 17000}], 'next_cursor': None},
    {'items': [{**bid(), 'next_action': 'auction_ended'}], 'next_cursor': None},
])
async def test_malformed_cross_owner_or_secret_source_fails_closed(payload):
    auction, orders = client('auction', payload), client('orders', {'items': [], 'next_cursor': None})
    try:
        result = await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
        assert result['bids'] == {'state': 'unavailable', 'items': [], 'next_cursor': None}
        assert result['reservations']['state'] == 'available'
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
async def test_independent_bulkhead_failure_does_not_make_empty_success():
    auction = client('auction', {}, 503)
    orders = client('orders', {'items': [reservation()], 'next_cursor': None})
    try:
        result = await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
        assert result['bids']['state'] == 'unavailable'
        assert result['reservations']['items'][0]['state'] == 'awaiting_payment'
        assert result['reservations']['items'][0]['payment_available'] is False
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
async def test_reservation_projection_is_owner_private_and_preserves_sample_label():
    auction = client('auction', {'items': [], 'next_cursor': None})
    orders = client('orders', {'items': [reservation()], 'next_cursor': None},
                    callback=lambda request: assert_path(request, '/v1/me/reservations'))
    try:
        result = await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
        items = result['reservations']['items']
        assert len(items) == 1 and items[0]['reservation_id'] == RESOURCE
        assert items[0]['next_action']['href'] == '/checkout?order=' + RESOURCE
        assert items[0]['is_demo'] is True
        assert all(private not in json.dumps(items) for private in ['buyer_id', 'seller_id', 'watch_id', 'organization_id'])
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['paid', 'released', 'completed', 'payment_unknown', 'expired_fenced'])
async def test_unreleased_payment_capability_cannot_enter_workspace_as_paid(state):
    auction = client('auction', {'items': [], 'next_cursor': None})
    orders = client('orders', {'items': [{**reservation(), 'state': state}], 'next_cursor': None})
    try:
        result = await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
        assert result['reservations']['state'] == 'unavailable'
        assert result['reservations']['items'] == []
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'buyer_id': OTHER}, {'is_demo': 'true'}, {'is_demo': None}])
async def test_reservation_scope_or_provenance_mismatch_fails_closed(changes):
    auction = client('auction', {'items': [], 'next_cursor': None})
    orders = client('orders', {'items': [{**reservation(), **changes}], 'next_cursor': None})
    try:
        result = await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
        assert result['reservations']['state'] == 'unavailable'
        assert result['reservations']['items'] == []
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
async def test_actual_timeout_is_an_independent_unavailable_section():
    async def delayed(request):
        await asyncio.sleep(.1)
        return httpx.Response(200, json={'items': [bid()], 'next_cursor': None})
    auction = DependencyClient('auction', 'http://auction', timeout=.02, transport=httpx.MockTransport(delayed))
    orders = client('orders', {'items': [reservation()], 'next_cursor': None})
    try:
        result = await asyncio.wait_for(compose(UUID(OWNER), 'private-token', 'request-6', auction, orders), timeout=.5)
        assert result['bids']['state'] == 'unavailable'
        assert result['reservations']['state'] == 'available'
        assert result['reservations']['items'][0]['state'] == 'awaiting_payment'
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
async def test_nested_dependency_budgets_leave_gateway_response_room():
    upstreams = routes.clients(FastAPI())
    try:
        assert upstreams['identity'].timeout + max(upstreams['auction'].timeout, upstreams['orders'].timeout) < 1.2
    finally:
        for dependency in upstreams.values():
            await dependency.aclose()


@pytest.mark.asyncio
async def test_revocation_denies_entire_workspace():
    auction, orders = client('auction', {}, 403), client('orders', {'items': [reservation()], 'next_cursor': None})
    try:
        with pytest.raises(AccessDenied):
            await compose(UUID(OWNER), 'private-token', 'request-6', auction, orders)
    finally:
        await auction.aclose()
        await orders.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('subject,session,roles', [(OTHER, 'session-6', ['buyer']), (OWNER, 'wrong', ['buyer']), (OWNER, 'session-6', ['operator'])])
async def test_route_requires_current_subject_lineage_and_buyer_role(monkeypatch, subject, session, roles):
    app = FastAPI()
    app.include_router(routes.router)
    app.state.l06_workspace_clients = {'identity': None}
    app.dependency_overrides[require_principal] = lambda: SimpleNamespace(subject=OWNER, session_id='session-6')
    async def principal(*args):
        return CurrentPrincipal.model_validate({'actor': {'subject_id': subject, 'session_id': session}, 'roles': roles})
    monkeypatch.setattr(routes, 'current_principal', principal)
    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id = 'request-6'
        return await call_next(request)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url='http://communications') as http:
        with pytest.raises(AccessDenied):
            await http.get('/v1/buyer-workspace', headers={'Authorization': 'Bearer private-token'})
