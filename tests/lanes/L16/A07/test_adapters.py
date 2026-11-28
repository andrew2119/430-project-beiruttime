import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from types import SimpleNamespace
from uuid import UUID
import httpx
import pytest
from fastapi import FastAPI
from bt_runtime.app.auth import require_principal
from bt_runtime.modules import discover
from bt_contracts_core.errors import AccessDenied
from bt_bulkheads import Unavailable

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'services').is_dir())
proxy = next(m for m in discover(ROOT / 'services/auction/modules') if m.id == 'L06.proxy')
private_router = proxy.load('private.py:router')
workspace = next(m for m in discover(ROOT / 'services/communications/modules') if m.id == 'L06.buyer-workspace')
compose = workspace.load('composition.py:compose_current')
workspace_router = workspace.load('routes.py:router')
workspace_route = workspace.load('routes.py:current_workspace')
OWNER = '00000000-0000-4000-8000-000000000001'
OTHER = '00000000-0000-4000-8000-000000000002'
AUCTION = '00000000-0000-4000-8000-000000000003'


@pytest.mark.asyncio
async def test_thousand_released_results_use_one_current_orders_snapshot_per_page():
    import asyncio
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from service_app import buyer_activity

    buyer = UUID(OWNER)
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    candidate_count = 4096
    rows = [dict(id=UUID(int=n + 2000), listing_id=UUID(int=n + 7000), watch_id=UUID(int=n + 12000),
                 order_id=UUID(int=n + 17000), winner_id=buyer, currency='USD', listing_is_demo=n % 2 == 0,
                 state='closed', result_revision=3, closing_minor=450000, ended_at=now) for n in range(candidate_count)]
    bindings = [dict(order_id=str(row['order_id']), auction_id=str(row['id']), watch_id=str(row['watch_id'])) for row in rows]
    matches = [binding for n, binding in enumerate(bindings) if n < 2000 and n % 2 == 0]
    changed, missing, overflow = False, False, False
    calls, local_reads = 0, 0
    selected = SimpleNamespace(actor=SimpleNamespace(subject_id=buyer, organization_id=None), roles=['buyer'], organizations=[])
    result_module = next(m for m in discover(ROOT / 'services/auction/modules') if m.id == 'L16.my-results')

    async def current(request):
        assert request.headers['authorization'] == 'Bearer current-buyer'
        return selected

    async def orders(service, method, path, request, *, headers, json):
        nonlocal calls
        calls += 1
        assert (service, method, path) == ('orders', 'POST', '/internal/v2/auction-financial-snapshot')
        assert headers == {'Authorization': 'Bearer signed-for-orders'}
        assert json == {'schema_version': 1, 'orders': bindings}
        await asyncio.sleep(.2)
        result = {'schema_version': 1, 'items': [dict(binding, revision=8 if changed and n == 500 else 7,
                  state='released' if n < 2000 and n % 2 == 0 and not (changed and n == 500) else 'unpaid_released')
                  for n, binding in enumerate(bindings[:-1] if missing else bindings)]}
        # Check the entire mixed candidate cohort fits the requested wire limits.
        assert len(httpx.Request('POST', 'http://orders', json=json).content) <= 672 * 1024
        assert len(httpx.Response(200, json=result).content) <= 896 * 1024
        return result

    class Database:
        async def fetch(self, statement, *args):
            nonlocal local_reads
            assert 'JOIN auction_lots' in statement and 'ORDER BY a.scheduled_ends_at' in statement
            assert args == (buyer, [], 'released', candidate_count + 1)
            local_reads += 1
            return [*rows, dict(rows[-1], id=UUID(int=30000), order_id=UUID(int=30001))] if overflow else rows

    @asynccontextmanager
    async def acquire():
        yield Database()

    auction = FastAPI()
    auction.include_router(buyer_activity.router)
    auction.state.pool = SimpleNamespace(acquire=acquire)
    auction.state.auction = SimpleNamespace(dependencies=SimpleNamespace(principal=current, json=orders,
        service_headers=lambda request, service: {'Authorization': 'Bearer signed-for-'+service}))
    auction.state.hooks = {'auction.my-results.project.v2': result_module.load('projection.py:project')}

    @auction.exception_handler(buyer_activity.PublicError)
    async def domain_error(_request: Request, error):
        return JSONResponse({'code': error.code}, status_code=error.status)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=auction), base_url='http://auction') as client:
        scoped = SimpleNamespace(request=client.request)
        async def read(cursor=None):
            return await compose(buyer, 'current-buyer', 'test-result', scoped, view='released', cursor=cursor)

        first = await read()
        assert first['state'] == 'available' and first['total'] == 1000
        assert [item['auction_id'] for item in first['items']] == [row['auction_id'] for row in matches[:50]]
        second = await read(first['next_cursor'])
        assert second['state'] == 'available' and second['total'] == 1000
        assert [item['auction_id'] for item in second['items']] == [row['auction_id'] for row in matches[50:100]]
        changed = True
        stale_cursor = workspace.load('composition.py:StaleActivityCursor')
        with pytest.raises(stale_cursor):
            await read(second['next_cursor'])
        fresh = await read()
        assert fresh['total'] == 999 and fresh['next_cursor'] != first['next_cursor']
        missing = True
        unavailable = await read()
        assert unavailable == dict(schema_version=2, state='unavailable', total=None, items=[], next_cursor=None)
        overflow = True
        assert await read() == unavailable
        assert calls == 5 and local_reads == 10


async def unused_provider_operation(*args):
    pytest.fail("Unexpected provider operation")


def app(provider=None):
    application = FastAPI()
    application.include_router(private_router)
    async def current():
        return SimpleNamespace(subject=OWNER)
    application.dependency_overrides[require_principal] = current
    if provider:
        application.state.proxy_private_v2 = provider
        application.state.auction = SimpleNamespace(bid_admission_version='auction.proxy.v2')
    return application


@pytest.mark.asyncio
@pytest.mark.parametrize('owner,standing,active,status', [
    (OWNER, 'outbid', False, 200),
    (OWNER, 'leading', False, 200),
    (OWNER, 'leading', True, 200),
    (OWNER, 'outbid', True, 503),
    (OWNER, 'unknown', False, 503),
    (OTHER, 'outbid', False, 403),
])
async def test_private_read_current_binding(owner, standing, active, status):
    async def read(request, auction):
        return dict(schema_version=2, auction_id=str(auction), actor_id=owner,
                    watch_id=AUCTION, revision=3, amount_minor=450000, active=active, standing=standing)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(SimpleNamespace(read_current=read))), base_url='http://auction') as client:
        result = await client.get('/v2/auctions/'+AUCTION+'/maximum')
    assert result.status_code == status
    if status == 200:
        assert result.headers['cache-control'] == 'no-store'
        assert result.json()['amount_minor'] == 450000
        assert result.json()['standing'] == standing
        assert result.json()['active'] is active
    else:
        assert '450000' not in result.text


@pytest.mark.asyncio
async def test_private_absent_timeout_and_revoked():
    async def timeout(*args):
        raise TimeoutError
    async def denied(*args):
        from fastapi import HTTPException
        raise HTTPException(403)
    for provider, status in [(None,503),(SimpleNamespace(read_current=timeout),503),(SimpleNamespace(read_current=denied),403)]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(provider)),base_url='http://auction') as client:
            result = await client.get('/v2/auctions/'+AUCTION+'/maximum')
        assert result.status_code == status


class Source:
    def __init__(self, body, status=200):
        self.body, self.status, self.paths = body, status, []

    async def request(self, method, path, headers):
        self.paths.append(path)
        assert method == 'GET' and headers['Authorization'] == 'Bearer synthetic-token'
        return httpx.Response(self.status,json=self.body)


def row(index=3):
    return dict(is_demo=True, auction_id=str(UUID(int=index)),listing_id=AUCTION,buyer_id=OWNER,
                status='leading',lifecycle='live',current_price_minor=430000,currency='USD',revision=3,
                starts_at='2030-01-01T00:00:00Z',ends_at='2030-01-02T00:00:00Z')


def activity_app(monkeypatch, source, *, identity_available=True):
    async def principal(*args):
        if not identity_available:
            return Unavailable('identity', 'timeout')
        actor = SimpleNamespace(subject_id=UUID(OWNER), session_id='test-session', organization_id=None)
        return SimpleNamespace(actor=actor, roles=['buyer'])

    monkeypatch.setitem(workspace_route.__globals__, 'current_principal', principal)
    application = FastAPI()
    application.include_router(workspace_router)
    application.state.l06_workspace_clients = {'identity': None, 'auction': source}

    async def verified():
        return SimpleNamespace(subject=OWNER, session_id='test-session')

    application.dependency_overrides[require_principal] = verified

    @application.middleware('http')
    async def request_reference(request, call_next):
        request.state.request_id = 'test-activity-read'
        return await call_next(request)

    return application


@pytest.mark.asyncio
@pytest.mark.parametrize('view', ['leading', 'outbid'])
async def test_thousand_rows_follow_buyer_workspace_cursors_and_source_totals(monkeypatch, view):
    class PagedSource:
        async def request(self, method, path, headers):
            assert method == 'GET'
            url = urlsplit(path)
            assert url.path == '/v2/my-bids'
            params = parse_qs(url.query)
            assert params['view'] == [view] and params['limit'] == ['50']
            cursor = params.get('cursor', [None])[0]
            offset = 0 if cursor is None else offsets[cursor]
            end = offset + 50
            next_cursor = f'test/page+{end}' if end < 1000 else None
            if next_cursor:
                offsets[next_cursor] = end
            return httpx.Response(200, json=dict(
                items=[dict(row(i), status=view) for i in range(offset+1, end+1)], total=1000, next_cursor=next_cursor))

    offsets = {}
    application = activity_app(monkeypatch, PagedSource())
    seen = []
    params = {'view': view}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        for page in range(20):
            response = await client.get('/v1/buyer-workspace', params=params)
            assert response.status_code == 200
            result = response.json()
            assert result['state'] == 'available' and result['total'] == 1000
            assert all('buyer_id' not in item for item in result['items'])
            seen.extend(item['auction_id'] for item in result['items'])
            cursor = result['next_cursor']
            assert (cursor is None) == (page == 19)
            params['cursor'] = cursor
    assert seen == [str(UUID(int=index)) for index in range(1, 1001)]


@pytest.mark.asyncio
async def test_stale_cursor_matches_fixture_and_allows_first_page_restart(monkeypatch):
    path = ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json'
    case = next(case for case in json.loads(path.read_text()) if case['case'] == 'stale')
    source = Source({}, case['http_status'])
    application = activity_app(monkeypatch, source)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        response = await client.get('/v1/buyer-workspace/v2', params={'cursor': 'test-stale'})
        assert response.status_code == case['http_status']
        assert response.json()['error']['code'] == case['error_code']
        assert response.headers['cache-control'] == 'no-store'
        source.body, source.status = dict(items=[], total=0, next_cursor=None), 200
        restarted = await client.get('/v1/buyer-workspace/v2')
        assert restarted.json() == dict(schema_version=2,state='available',items=[],total=0,next_cursor=None)


@pytest.mark.asyncio
async def test_auction_timeout_matches_workspace_fixture(monkeypatch):
    path = ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json'
    case = next(case for case in json.loads(path.read_text()) if case['case'] == 'lost_response')

    class TimedOutSource:
        async def request(self, method, path, headers):
            raise TimeoutError

    application = activity_app(monkeypatch, TimedOutSource())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        response = await client.get('/v1/buyer-workspace/v2')
    assert response.status_code == case['http_status']
    assert response.json() == case['response']
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.asyncio
async def test_identity_timeout_fails_before_auction_read(monkeypatch):
    source = Source(dict(items=[row()], total=1))
    application = activity_app(monkeypatch, source, identity_available=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        response = await client.get('/v1/buyer-workspace/v2')
    assert response.status_code == 503
    assert 'state' not in response.json()
    assert source.paths == []


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [dict(items=[dict(row(),buyer_id=OTHER)],total=1),dict(items=[dict(row(),amount_minor=450000)],total=1),dict(items=[row()],total=0),dict(items=[dict(row(),status='outbid')],total=1)])
async def test_foreign_private_invalid_and_mismatched_pages_unavailable(body):
    result = await compose(UUID(OWNER),'synthetic-token','read-1',Source(body),view='leading')
    assert result == dict(schema_version=2,state='unavailable',items=[],total=None,next_cursor=None)


@pytest.mark.asyncio
async def test_denied_and_timeout_never_become_empty_success():
    with pytest.raises(AccessDenied):
        await compose(UUID(OWNER),'synthetic-token','read-1',Source({},403),view='won')
    class Timeout:
        async def request(self,*args,**kwargs):
            raise TimeoutError
    result = await compose(UUID(OWNER),'synthetic-token','read-1',Timeout(),view='won')
    assert result['state'] == 'unavailable'


def command_body(case):
    return dict(amount_minor=450000, fee_quote_id=case['quote_id'], expected_revision=case['expected_revision'],
                watch_id=case['watch_id'], quote_revision=case['quote_revision'], policy_revision=case['policy_revision'])


@pytest.mark.asyncio
async def test_operation_fixtures_lookup_and_stable_submit():
    import json
    cases = json.loads((ROOT / 'packages/contracts-auction/proxy/fixtures/operations.v2.json').read_text())
    for case in cases:
        async def lookup(request, auction, operation):
            return case
        async def submit(request, auction, command):
            assert str(auction) == case['subject_id']
            assert request.headers['idempotency-key'] == case['operation_id']
            return case
        application = app(SimpleNamespace(read_current=unused_provider_operation, lookup_current=lookup, submit_current=submit))
        # The receipt actor is a deterministic contract identity.
        async def current():
            return SimpleNamespace(subject=case['actor_id'])
        application.dependency_overrides[require_principal] = current
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url='http://auction') as client:
            path = '/v2/auctions/'+case['subject_id']+'/maximum'
            read = await client.get(path+'/operations/'+case['operation_id'])
            assert read.status_code == 200 and read.json() == case
            for _ in range(2):
                sent = await client.post(path,headers={'Idempotency-Key':case['operation_id']},json=command_body(case))
                assert sent.status_code == 200 and sent.json() == case
                assert sent.headers['cache-control'] == 'no-store'
                assert 'amount_minor' not in sent.text


@pytest.mark.asyncio
async def test_published_current_result_fixture_and_wrong_utc():
    import json
    cases = json.loads((ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json').read_text())
    case = cases[0]
    result = await compose(UUID(OWNER),'synthetic-token','read-1',Source(case['source']),view='won')
    assert result == case['response']
    malformed = dict(case['source'])
    malformed['items'] = [dict(malformed['items'][0],ended_at='2030-01-01T02:00:00+02:00')]
    assert (await compose(UUID(OWNER),'synthetic-token','read-1',Source(malformed),view='won'))['state'] == 'unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [dict(expected_revision=1),dict(quote_id=OTHER),dict(watch_id=OTHER),dict(quote_revision=2),dict(policy_revision='test-other-policy'),dict(actor_id='00000000-0000-4000-8000-000000000099'),dict(operation_id=OTHER),dict(subject_id=OTHER)])
async def test_submit_receipt_must_match_immutable_command(change):
    import json
    case = json.loads((ROOT / 'packages/contracts-auction/proxy/fixtures/operations.v2.json').read_text())[0]
    async def submit(*args):
        return dict(case,**change)
    application = app(SimpleNamespace(read_current=unused_provider_operation,
                                      lookup_current=unused_provider_operation, submit_current=submit))
    async def current():
        return SimpleNamespace(subject=case['actor_id'])
    application.dependency_overrides[require_principal] = current
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url='http://auction') as client:
        result = await client.post('/v2/auctions/'+case['subject_id']+'/maximum',headers={'Idempotency-Key':case['operation_id']},json=command_body(case))
    assert result.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize('view', ['leading', 'won'])
async def test_requested_page_limit_is_enforced(view):
    import json
    template = json.loads((ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json').read_text())[0]['source']['items'][0]
    for count in (50, 51):
        items = [dict(row(index + 1) if view == 'leading' else template, auction_id=str(UUID(int=index + 1))) for index in range(count)]
        body = dict(items=items, total=1000, next_cursor='next')
        if view == 'won':
            body.update(schema_version=2, state='available')
        result = await compose(UUID(OWNER), 'synthetic-token', 'read-1', Source(body), view=view)
        assert result['state'] == ('available' if count == 50 else 'unavailable')
        if count == 51:
            assert result['items'] == [] and result['total'] is None and result['next_cursor'] is None


@pytest.mark.asyncio
async def test_scheduled_calendar_row_has_no_bid_standing():
    scheduled = dict(row(), lifecycle='scheduled', status=None, current_price_minor=0)
    page = await compose(UUID(OWNER), 'synthetic-token', 'read-1',
                         Source(dict(items=[scheduled], total=1)), view='calendar')
    assert page['state'] == 'available' and page['items'][0]['status'] is None

    for view, item in [('leading', scheduled), ('calendar', dict(scheduled, status='outbid')),
                       ('calendar', dict(scheduled, current_price_minor=430000)),
                       ('leading', dict(row(), current_price_minor=0))]:
        page = await compose(UUID(OWNER), 'synthetic-token', 'read-1',
                             Source(dict(items=[item], total=1)), view=view)
        assert page['state'] == 'unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('lifecycle,status', [('scheduled', None), ('live', 'leading')])
@pytest.mark.parametrize('end,available', [
    ('2029-12-31T23:59:59Z', False),
    ('2030-01-01T00:00:00Z', False),
    ('2030-01-01T00:00:01Z', True),
    ('2030-04-01T00:00:00Z', True),
    ('2030-04-01T00:00:01Z', False),
])
async def test_calendar_requires_positive_length_at_most_ninety_days(lifecycle, status, end, available):
    item = dict(row(), lifecycle=lifecycle, status=status, ends_at=end,
                current_price_minor=0 if lifecycle == 'scheduled' else 430000)
    page = await compose(UUID(OWNER), 'synthetic-token', 'read-1',
                         Source(dict(items=[item], total=1)), view='calendar')
    if available:
        assert page['state'] == 'available' and len(page['items']) == 1
    else:
        assert page == dict(schema_version=2, state='unavailable', items=[], total=None, next_cursor=None)


@pytest.mark.asyncio
@pytest.mark.parametrize('view,field_name', [('calendar', 'starts_at'), ('calendar', 'ends_at'), ('won', 'ended_at')])
@pytest.mark.parametrize('malformed', [1893456000, 1893456000.25, '1893456000', '2030-01-01 00:00:00Z',
                                       '2030-01-01T00:00:00+01:00', '2030-01-01T00:00Z'])
async def test_current_activity_rejects_noncontract_instants(view, field_name, malformed):
    if view == 'won':
        fixture = ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json'
        item = json.loads(fixture.read_text())[0]['source']['items'][0]
        body = dict(schema_version=2, state='available', items=[item], total=1)
    else:
        item = dict(row(), lifecycle='scheduled', status=None, current_price_minor=0)
        body = dict(items=[item], total=1)
    item[field_name] = malformed
    page = await compose(UUID(OWNER), 'synthetic-token', 'read-1', Source(body), view=view)
    assert page == dict(schema_version=2, state='unavailable', items=[], total=None, next_cursor=None)


@pytest.mark.asyncio
@pytest.mark.parametrize('view', ['lost', 'released'])
@pytest.mark.parametrize('completed', [False, True])
async def test_archive_filters_completion_independently_of_standing(view, completed):
    import json
    path = ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json'
    source = json.loads(path.read_text())[0]['source']
    source['items'][0].update(state='lost', completed_sale=completed, order_id=None, financial_state=None, next_action='view_auction')
    page = await compose(UUID(OWNER), 'synthetic-token', 'read-1', Source(source), view=view)
    if view == 'released' and not completed:
        assert page['state'] == 'unavailable'
    else:
        assert page['items'][0]['state'] == 'lost'
        assert page['items'][0]['completed_sale'] is completed
        assert page['items'][0]['order_id'] is None


@pytest.mark.asyncio
async def test_accepted_receipt_without_revision_advance_is_unavailable():
    path = ROOT / 'packages/contracts-auction/proxy/fixtures/operations.v2.json'
    case = json.loads(path.read_text())[0]

    async def provider(*args):
        return dict(case, revision=case['expected_revision'])

    application = app(SimpleNamespace(read_current=unused_provider_operation, submit_current=provider, lookup_current=provider))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://auction') as client:
        maximum = '/v2/auctions/' + case['subject_id'] + '/maximum'
        lookup = await client.get(maximum + '/operations/' + case['operation_id'])
        sent = await client.post(maximum, headers={'Idempotency-Key': case['operation_id']}, json=command_body(case))
    assert lookup.status_code == sent.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize('original_arrived', [False, True])
async def test_replay_resolves_original_key_after_revision_changes(original_arrived):
    case = json.loads((ROOT / 'packages/contracts-auction/proxy/fixtures/operations.v2.json').read_text())[0]
    auction_revision = case['expected_revision']
    receipts = {}
    admissions = 0

    async def submit(request, auction, command):
        nonlocal admissions
        key = request.headers['Idempotency-Key']
        assert str(auction) == case['subject_id']
        assert key == case['operation_id']
        body = command.model_dump(mode='json')
        assert body == command_body(case)
        if key not in receipts:
            if command.expected_revision == auction_revision:
                admissions += 1
                receipt = case
            else:
                receipt = dict(case, state='stale', revision=auction_revision)
            receipts[key] = receipt
        return receipts[key]

    async def lookup(request, auction, operation):
        from fastapi import HTTPException
        receipt = receipts.get(str(operation))
        if receipt is None:
            raise HTTPException(404)
        return receipt

    async def actor():
        return SimpleNamespace(subject=case['actor_id'])

    application = app(SimpleNamespace(read_current=unused_provider_operation, submit_current=submit, lookup_current=lookup))
    application.dependency_overrides[require_principal] = actor
    transport = httpx.ASGITransport(app=application)
    path = '/v2/auctions/' + case['subject_id'] + '/maximum'
    headers = {'Idempotency-Key': case['operation_id']}
    async with httpx.AsyncClient(transport=transport, base_url='http://auction') as client:
        if original_arrived:
            await client.post(path, headers=headers, json=command_body(case))
        auction_revision = case['revision'] + 1
        lookup_path = path + '/operations/' + case['operation_id']
        lookup_response = await client.get(lookup_path)
        assert lookup_response.status_code == (200 if original_arrived else 404)
        replay = await client.post(path, headers=headers, json=command_body(case))
        assert replay.status_code == 200
        assert replay.json()['state'] == ('accepted' if original_arrived else 'stale')
        assert (await client.get(lookup_path)).json() == replay.json()
        assert (await client.post(path, headers=headers, json=command_body(case))).json() == replay.json()
    assert admissions == int(original_arrived)


@pytest.mark.asyncio
@pytest.mark.parametrize('financial,action', [
    ('pending', 'review_order'),
    ('unknown', 'contact_support'),
    ('paid_held', 'review_order'),
])
async def test_winner_payment_status_and_next_action_are_projected(financial, action):
    path = ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json'
    source = json.loads(path.read_text())[0]['source']
    source['items'][0].update(financial_state=financial, next_action=action)
    page = await compose(UUID(OWNER), 'synthetic-token', 'read-1', Source(source), view='won')
    assert page['items'][0]['state'] == 'won'
    assert page['items'][0]['financial_state'] == financial
    assert page['items'][0]['next_action'] == action

    source['items'][0]['state'] = 'lost'
    source['items'][0]['order_id'] = None
    source['items'][0]['next_action'] = 'view_auction'
    page = await compose(UUID(OWNER), 'synthetic-token', 'read-1', Source(source), view='lost')
    assert page['state'] == 'unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('financial,matching_views', [
    ('unpaid', {'won', 'unpaid'}),
    ('unpaid_released', {'won', 'unpaid'}),
    ('released', {'won', 'released'}),
])
async def test_won_view_keeps_winners_through_payment_changes(financial, matching_views):
    path = ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json'
    source = json.loads(path.read_text())[0]['source']
    source['items'][0].update(financial_state=financial, completed_sale=financial == 'released')
    for view in ('won', 'unpaid', 'released'):
        page = await compose(UUID(OWNER), 'synthetic-token', 'read-1', Source(source), view=view)
        if view in matching_views:
            assert page['items'][0]['state'] == 'won'
            assert page['items'][0]['financial_state'] == financial
        else:
            assert page['state'] == 'unavailable'


def test_canonical_default_admits_ordinary_manual_bids_without_creating_ceilings():
    from service_app.engine import AuctionEngine
    from service_app.proxy_v2 import calculate as hook
    state = dict(opening_minor=400000, current_minor=400000, leader_id=None,
                 sequence=0, increment_bands=[dict(from_minor=0, step_minor=10000)], maxima=[])
    for sequence, (bidder, amount) in enumerate([(OWNER, 400000), (OTHER, 410000), (OWNER, 420000)], 1):
        command = dict(kind='manual', bidder_id=bidder, amount_minor=amount, sequence=sequence)
        result = hook(state, command)
        AuctionEngine.validate_result(state, command, result)
        assert result['leader_id'] == bidder
        assert result['maxima'] == []
        assert result['bids'] == [dict(bidder_id=bidder, amount_minor=amount, automatic=False)]
        state.update(leader_id=result['leader_id'], current_minor=result['current_minor'],
                     maxima=result['maxima'], sequence=sequence)


@pytest.mark.asyncio
@pytest.mark.parametrize(('kind', 'current', 'amount', 'expected_bids', 'expected_outbid'), [
    ('manual', 445000, 460000, [(OTHER, 460000, False)], OWNER),
    ('manual', 410000, 420000, [(OTHER, 420000, False)], OWNER),
    ('manual', 0, 400000, [(OTHER, 400000, False)], None),
    ('manual', 430000, 450001, [(OTHER, 450001, False)], OWNER),
    ('manual', 400000, 420000, [(OTHER, 420000, False), (OWNER, 430000, True)], OTHER),
    ('manual', 430000, 440000, [(OTHER, 440000, False), (OWNER, 450000, True)], OTHER),
    *[
        ('manual', 430000, amount, [(OTHER, amount, False)], OWNER)
        for amount in (440001, 445000, 450000)
    ],
    ('maximum', 430000, 450000, [(OTHER, 450000, True)], OWNER),
    ('maximum', 0, 450000, [(OTHER, 400000, True)], None),
])
async def test_registered_admission_and_notice_cutover(
    kind, current, amount, expected_bids, expected_outbid, monkeypatch,
):
    from service_app import engine
    from bt_contracts.auction.core.models import BidAcceptedEventData
    from bt_contracts.auction.proxy.notices import accepted_bid_notices
    from service_app.private_maximum import PrivateMaximum

    assert engine.AuctionEngine.bid_admission_version == 'auction.proxy.v2'
    from contextlib import asynccontextmanager
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock

    auction = UUID(AUCTION)
    challenger = UUID(OTHER)
    seller = UUID(int=42)
    now = datetime.now(timezone.utc)
    ends = now + timedelta(hours=1)
    lot = dict(id=auction, listing_id=auction, watch_id=auction, seller_id=seller, seller_organization_id=None,
               listing_revision=1, mode='bidding', first_bid_confirmed=True, end_version=1,
               starts_at=now - timedelta(hours=1), ends_at=ends, scheduled_ends_at=ends,
               currency='USD', revision=3, accepted_sequence=3, leader_id=UUID(OWNER),
               opening_minor=400000, current_minor=current, high_value_minor=1000000,
               increment_bands=[dict(from_minor=0, step_minor=10000)])
    caps = [dict(bidder_id=UUID(OWNER), amount_minor=450000, sequence=1, active=True)]
    if current == 410000:
        caps = []
    if current == 0:
        lot.update(leader_id=None, accepted_sequence=0)
        caps.clear()
    if current == 445000:
        # The manual challenger regains the lead without changing the displaced ceiling.
        caps[:] = [dict(bidder_id=challenger, amount_minor=450000, sequence=1, active=False)]
    prior_sequence = lot['accepted_sequence']
    receipts, bids, events = {}, [], []
    active = False

    class Transaction:
        async def execute(self, sql, *args):
            assert active
            if 'pg_advisory_xact_lock' in sql:
                return
            if 'INSERT INTO auction_bids' in sql:
                bids.append(args)
            elif 'UPDATE auction_maxima SET active=false' in sql:
                assert args == (auction,)
                for row in caps:
                    row['active'] = False
            elif 'INSERT INTO auction_maxima' in sql:
                resource, bidder, amount, sequence, activity = args
                assert resource == auction and type(activity) is bool
                caps[:] = [row for row in caps if row['bidder_id'] != bidder]
                caps.append(dict(bidder_id=bidder, amount_minor=amount, sequence=sequence, active=activity))
            else:
                assert 'INSERT INTO auction_operations' in sql
                _, subject, organization, key, digest, resource, outcome, *binding = args
                assert resource == auction and (subject, key) not in receipts
                receipts[subject, key] = dict(request_hash=digest, organization_id=organization, auction_id=resource,
                    private_maximum_binding=json.loads(binding[0]) if binding else None, outcome=json.loads(outcome))

        async def fetchrow(self, sql, *args):
            assert active
            if 'SELECT * FROM auction_operations' in sql:
                return receipts.get(args)
            if 'FROM auction_lots AS a LEFT JOIN auction_maxima' in sql:
                assert 'm.verified_ceiling' in sql and args[0] == auction
                who = args[1]
                own = next((row for row in caps if row['bidder_id'] == who), None)
                return dict(lot, own_ceiling=own['amount_minor'] if own else None,
                            own_active=own['active'] if own else None,
                            has_bid=any(owner == who for owner, _ in receipts))
            if 'FROM auction_lots' in sql:
                assert args == (auction,)
                return dict(lot)
            assert 'UPDATE auction_lots' in sql
            resource, amount, leader, sequence, ends_at, end_version = args
            assert resource == auction and ends_at == ends and end_version == 1
            lot.update(current_minor=amount, leader_id=leader, accepted_sequence=sequence,
                       revision=lot['revision'] + 1)
            return lot

        def transaction(self, **options):
            return transaction(None)

        async def fetch(self, sql, *args):
            assert active and 'FROM auction_maxima' in sql and 'verified_ceiling' in sql and args == (auction,)
            return [row.copy() for row in caps]

        async def fetchval(self, sql, *args):
            assert active
            if 'FROM auction_publication_watermarks' in sql:
                assert args == (auction,)
                return 1
            assert sql == 'SELECT clock_timestamp()' and not args
            return now

    @asynccontextmanager
    async def transaction(pool):
        nonlocal active
        active = True
        try:
            yield Transaction()
        finally:
            active = False

    async def enqueue(tx, event, recipients):
        expected = {'auction.bid-accepted.v1': ['communications'],
                    'auction.bid-outbid.v2': ['bid-notices-v2'],
                    'auction.timing-updated.v2': ['auction-timing-v2']}
        assert active and recipients == expected[event.type]
        events.append(event)

    monkeypatch.setattr(engine, 'unit_of_work', transaction)
    monkeypatch.setattr(engine, 'enqueue', enqueue)
    principal = SimpleNamespace(actor=SimpleNamespace(subject_id=challenger, organization_id=None),
                                roles=['buyer'], organizations=[], permissions=[])
    async def held_admission(request, tx, actor):
        assert active and isinstance(tx, Transaction) and actor is principal

    async def reviewed_quote(request, command, snapshot, actor):
        assert actor is principal and snapshot['id'] == auction
        assert (command.expected_revision, command.fee_quote_id) in ((3, auction), (4, UUID(int=23)))
        return SimpleNamespace(id=command.fee_quote_id, revision=1, expires_at=ends, policy=SimpleNamespace(revision=2))

    dependencies = SimpleNamespace(
        principal=AsyncMock(return_value=principal),
        bid_admission=AsyncMock(side_effect=held_admission),
        listing=AsyncMock(return_value=dict(id=AUCTION, watch_id=AUCTION,
                                            seller_id=str(seller), revision=1, status='published')),
        check_fence=AsyncMock(),
        fee=AsyncMock(return_value=lot['ends_at']),
        bid_quote=AsyncMock(side_effect=reviewed_quote),
    )
    hooks = {key: proxy.load(hook) for key, hook in proxy.hooks.items()}
    state = SimpleNamespace(pool=SimpleNamespace(acquire=lambda **kwargs: transaction(None)), hooks=hooks)
    request = SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace(request_id='test-request'),
                              headers=httpx.Headers({'Idempotency-Key': 'test-original-bid'}))
    command = proxy.load('private.py:MaximumCommand')(
        amount_minor=amount, fee_quote_id=auction, expected_revision=3,
    )
    admission = engine.AuctionEngine(dependencies)

    manual_route = next(
        module for module in discover(ROOT / 'services/auction/modules')
        if module.id == 'L05.b-bid-admission'
    ).load('routes.py:bid')
    state.auction = admission

    denied_count = 0
    if kind == 'manual':
        receipt = await manual_route(auction, command, request)
        assert await manual_route(auction, command, request) == receipt
        dependencies.fee.assert_awaited_once()
    else:
        # Exercise the published direct route with the A10 three-field body.
        application = app()
        application.state.auction = admission
        application.state.pool = state.pool
        application.state.hooks = hooks
        application.state.proxy_private_v2 = PrivateMaximum(admission)
        from fastapi.responses import JSONResponse

        @application.exception_handler(engine.PublicError)
        async def public_error(request, error):
            return JSONResponse({'code': error.code}, status_code=error.status)

        @application.middleware('http')
        async def request_id(request, call_next):
            request.state.request_id = 'test-request'
            return await call_next(request)

        async def buyer_token():
            return SimpleNamespace(subject=str(principal.actor.subject_id))

        application.dependency_overrides[require_principal] = buyer_token
        key = str(UUID(int=21))
        path = f'/v2/auctions/{auction}/maximum'
        body = command.model_dump(mode='json')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://auction') as client:
            response = await client.post(path, json=body, headers={'Idempotency-Key': key})
            assert response.status_code == 200
            assert response.json() == dict(schema_version=2, operation_id=key, actor_id=OTHER, organization_id=None,
                subject_id=AUCTION, watch_id=AUCTION, expected_revision=3, revision=4, quote_id=AUCTION,
                quote_revision=1, policy_revision='2', state='accepted', pending_reason=None, next_actor=None,
                next_review_at=None)
            assert (await client.post(path, json=body, headers={'Idempotency-Key': key})).json() == response.json()
            assert (await client.get(f'{path}/operations/{key}')).json() == response.json()
            assert (await client.get(path)).json()['amount_minor'] == amount
            principal.permissions.append(engine.SUSPENDED_ACTIVITY)
            assert (await client.post(path, json=body, headers={'Idempotency-Key': key})).json() == response.json()
            assert (await client.get(f'{path}/operations/{key}')).json() == response.json()
            assert (await client.get(path)).json()['amount_minor'] == amount
            suspended_key = str(UUID(int=22))
            denied_path = f'{path}/operations/{suspended_key}'
            denied_body = dict(body, expected_revision=4, fee_quote_id=str(UUID(int=23)), amount_minor=amount + 10000)
            assert (await client.get(denied_path)).status_code == 404
            refused = await client.post(path, json=denied_body, headers={'Idempotency-Key': suspended_key})
            assert refused.status_code == 200
            assert refused.json() == dict(response.json(), operation_id=suspended_key, expected_revision=4,
                                          quote_id=denied_body['fee_quote_id'], state='denied')
            assert (await client.get(denied_path)).json() == refused.json()
            assert receipts[challenger, suspended_key]['outcome']['code'] == 'bid_permission_required'
            principal.permissions.clear()
            assert (await client.post(path, json=denied_body, headers={'Idempotency-Key': suspended_key})).json() == refused.json()
            assert (await client.post(path, json=dict(denied_body, amount_minor=amount + 1),
                                      headers={'Idempotency-Key': suspended_key})).status_code == 409
            denied_count = 1
            principal.actor.subject_id = UUID(OWNER)
            assert (await client.get(path)).json()['amount_minor'] == (450000 if current else None)
            assert (await client.get(f'{path}/operations/{key}')).status_code == 404
            assert (await client.get(denied_path)).status_code == 404
            principal.actor.subject_id = challenger
        receipt = receipts[challenger, key]['outcome']
        assert dependencies.bid_quote.await_count == 2
        dependencies.fee.assert_not_awaited()
    assert receipt['status'] == 'succeeded' and receipt['revision'] == 4
    assert len(receipts) == 1 + denied_count
    dependencies.bid_admission.assert_awaited_once()
    assert [event.type for event in events].count('auction.bid-accepted.v1') == 1
    assert [event.type for event in events].count('auction.timing-updated.v2') == 1
    assert all(str(operation) == receipt['operation_id'] for _, _, operation, *_ in bids)
    assert all('maxima' not in event.data for event in events) and 'maxima' not in receipt
    actual_bids = [(str(who), cents, automatic) for _, _, _, who, cents, automatic, _ in bids]
    leader, price, _ = actual_bids[-1]
    assert [seq for _, seq, *_ in bids] == list(range(prior_sequence + 1, prior_sequence + len(bids) + 1))
    assert receipt['accepted_sequence'] == prior_sequence + len(bids)
    assert receipt['current_minor'] == events[0].data['current_minor'] == lot['current_minor'] == price
    assert events[0].data['leader_id'] == str(lot['leader_id']) == leader
    challenger_events = [event for event in events if event.type == 'auction.bid-outbid.v2']
    assert len(challenger_events) == int(leader != OTHER)
    if challenger_events:
        assert challenger_events[0].data['bidder_id'] == OTHER
        assert challenger_events[0].data['revision'] == receipt['revision']
    event_facts = BidAcceptedEventData.model_validate(events[0].data)
    planned_notices = [(OTHER, 'bid_accepted')]
    if prior_sequence and leader != OTHER:
        planned_notices.append((OTHER, 'outbid'))
    elif prior_sequence and leader != OWNER:
        planned_notices.append((OWNER, 'outbid'))
    assert [(str(recipient), kind) for recipient, kind in accepted_bid_notices(
        bidder_id=event_facts.bidder_id,
        previous_leader_id=event_facts.previous_leader_id,
        leader_id=event_facts.leader_id,
    )] == planned_notices

    notice_module = next(
        module for module in discover(ROOT / 'services/communications/modules')
        if module.id == 'L05.bid-notices'
    )
    consume = notice_module.load('events.py:accepted')
    writes = {}

    class NoticeTransaction:
        async def execute(self, sql, *args):
            assert 'ON CONFLICT(event_id,recipient_id,kind) DO NOTHING' in sql
            notice_id, event_id, recipient, notice_kind, *facts = args
            assert event_id == events[0].id
            assert tuple(facts) == (
                auction, auction, receipt['accepted_sequence'], price, 'USD',
                lot['ends_at'], now, receipt['revision'],
            )
            key = (event_id, str(recipient), notice_kind)
            assert writes.setdefault(key, notice_id) == notice_id

    await consume(NoticeTransaction(), events[0])
    await consume(NoticeTransaction(), events[0])
    installed = [(recipient, notice_kind) for _, recipient, notice_kind in writes]
    assert actual_bids == expected_bids
    assert installed == planned_notices
    assert [recipient for recipient, notice_kind in installed if notice_kind == 'outbid'] == (
        [] if expected_outbid is None else [expected_outbid]
    )
    expected_caps = {}
    if current == 445000:
        expected_caps[challenger] = dict(bidder_id=challenger, amount_minor=450000, sequence=1, active=False)
    elif current not in (0, 410000):
        expected_caps[UUID(OWNER)] = dict(
            bidder_id=UUID(OWNER), amount_minor=450000, sequence=1, active=leader == OWNER,
        )
    if kind == 'maximum':
        expected_caps[challenger] = dict(
            bidder_id=challenger, amount_minor=amount, sequence=prior_sequence + 1, active=True,
        )
    assert {row['bidder_id']: row for row in caps} == expected_caps


@pytest.mark.asyncio
@pytest.mark.parametrize('view', ['leading', 'won'])
async def test_first_page_with_more_rows_requires_a_continuation(view):
    if view == 'leading':
        body = dict(items=[row()], total=1000)
    else:
        path = ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json'
        body = dict(json.loads(path.read_text())[0]['source'], total=1000)
    for next_cursor in (None, ''):
        page = await compose(UUID(OWNER), 'synthetic-token', 'read-1',
                             Source(dict(body, next_cursor=next_cursor)), view=view)
        assert page == dict(schema_version=2, state='unavailable', items=[], total=None, next_cursor=None)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/v1/buyer-workspace', '/v1/buyer-workspace/v2'])
async def test_activity_route_rejects_a_nonadvancing_continuation(monkeypatch, path):
    source = Source(dict(items=[row()], total=1000, next_cursor='test-same'))
    application = activity_app(monkeypatch, source)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        response = await client.get(path, params={'view': 'leading', 'cursor': 'test-same'})
    assert response.status_code == 200
    assert response.json() == dict(schema_version=2, state='unavailable', items=[], total=None, next_cursor=None)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/v1/buyer-workspace', '/v1/buyer-workspace/v2'])
@pytest.mark.parametrize('view', ['leading', 'outbid', 'calendar', 'won', 'lost', 'no_sale', 'unpaid', 'released'])
@pytest.mark.parametrize('cursor', [None, 'test-previous-page'])
async def test_activity_never_substitutes_a_different_producer(monkeypatch, path, view, cursor):
    fixture = ROOT / 'packages/contracts-comms/buyer-workspace/fixtures/current.v2.json'
    case = next(case for case in json.loads(fixture.read_text()) if case['case'] == 'producer_absent')
    requested = []

    class AbsentSource:
        async def request(self, method, path, headers):
            requested.append(path)
            url = urlsplit(path)
            assert url.path == ('/v2/my-bids' if view in ('leading', 'outbid', 'calendar') else '/v2/my-results')
            assert parse_qs(url.query) == {'limit': ['50'], 'view': [view], **({'cursor': [cursor]} if cursor else {})}
            return httpx.Response(404)

    application = activity_app(monkeypatch, AbsentSource())
    params = {'view': view, **({'cursor': cursor} if cursor else {})}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        response = await client.get(path, params=params)
    assert response.status_code == case['http_status'] and response.json() == case['response']
    assert len(requested) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_available', [False, True])
async def test_registered_maximum_v2_operations_use_only_the_current_provider(provider_available, monkeypatch):
    from contextlib import asynccontextmanager
    from service_app import engine

    class Transaction:
        async def fetchrow(self, sql, *args):
            return dict(revision=3, seller_id=UUID(OWNER), seller_organization_id=None)

    @asynccontextmanager
    async def transaction(pool):
        yield Transaction()

    monkeypatch.setattr(engine, 'unit_of_work', transaction)
    from bt_runtime.app.main import create_app
    from bt_runtime.app.settings import Settings

    case = json.loads((ROOT / 'packages/contracts-auction/proxy/fixtures/operations.v2.json').read_text())[0]
    actor = case['actor_id']
    auction_id = case['subject_id']
    application = create_app(Settings(service_name='auction', database_url='postgresql://unused/unused',
                                      modules_path=ROOT / 'services/auction/modules/proxy'))
    async def current():
        return SimpleNamespace(subject=actor)

    application.dependency_overrides[require_principal] = current
    calls = []

    legacy_calls = []

    async def legacy_submit(request, auction, command, *, kind):
        legacy_calls.append((str(auction), request.headers['Idempotency-Key'], command.amount_minor, kind))
        return {'status': 'succeeded', 'revision': 4}

    async def read(request, auction):
        calls.append(('read', str(auction)))
        return dict(schema_version=2, auction_id=auction_id, actor_id=actor,
                    watch_id=case['watch_id'], revision=3, amount_minor=450000,
                    active=True, standing='leading')

    async def lookup(request, auction, operation):
        calls.append(('lookup', str(auction), str(operation)))
        return case

    async def submit(request, auction, command):
        calls.append(('submit', str(auction), request.headers['Idempotency-Key'],
                      command.model_dump(mode='json')))
        return case

    async def legacy_principal(request):
        return SimpleNamespace(roles=['buyer'], organizations=[], actor=SimpleNamespace(subject_id=UUID(actor), organization_id=None))

    application.state.auction = SimpleNamespace(
        submit=legacy_submit, dependencies=SimpleNamespace(principal=legacy_principal),
        bid_admission_version='auction.proxy.v2' if provider_available else None)
    application.state.pool = None
    if provider_available:
        application.state.proxy_private_v2 = SimpleNamespace(
            read_current=read, lookup_current=lookup, submit_current=submit)
    path = f'/v1/auctions/{auction_id}/maximum'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://auction') as client:
        own = await client.post(path, json={'action': 'read_v2'})
        body = {'action': 'submit_v2', 'command': command_body(case)}
        sent = await client.post(path, json=body, headers={'Idempotency-Key': case['operation_id']})
        receipt = await client.post(path, json={'action': 'lookup_v2', 'operation_id': case['operation_id']})
        malformed = await client.post(path, json=dict(body['command'], action='submit_v2'))
        assert not legacy_calls
    assert malformed.status_code == 422
    assert '450000' not in malformed.text
    if provider_available:
        assert own.status_code == sent.status_code == receipt.status_code == 200
        assert own.json()['amount_minor'] == 450000 and own.headers['cache-control'] == 'no-store'
        assert sent.json() == receipt.json() == case
        assert '450000' not in sent.text and '450000' not in receipt.text
        assert calls == [('read', auction_id),
                         ('submit', auction_id, case['operation_id'], command_body(case)),
                         ('lookup', auction_id, case['operation_id'])]
    else:
        assert own.status_code == 200
        assert own.json() == dict(schema_version=1, auction_id=auction_id, actor_id=actor, revision=3)
        assert sent.status_code == receipt.status_code == 503
        assert calls == []


@pytest.mark.asyncio
async def test_canonical_transaction_replays_old_receipt_without_reentering_competition(monkeypatch):
    from contextlib import asynccontextmanager
    from fastapi.responses import JSONResponse

    from service_app import engine

    seller_business = UUID(int=12)
    command_type = proxy.load('private.py:MaximumCommand')
    command = command_type(amount_minor=450000, fee_quote_id=UUID(OTHER), expected_revision=2)
    lot = dict(revision=3, watch_id=UUID(OTHER), seller_id=UUID(OTHER), seller_organization_id=seller_business)
    receipt = dict(operation_id=OTHER, auction_id=AUCTION, status='succeeded',
                   code='bid_accepted', revision=3, accepted_sequence=1, current_minor=400000,
                   next_minimum_minor=410000, end_version=1, mode='bidding',
                   ends_at='2030-01-02T10:00:00Z', server_time='2030-01-01T10:00:00Z')
    organizations = []
    looked_up = []

    class Transaction:
        async def execute(self, sql, *args):
            assert 'pg_advisory_xact_lock' in sql

        async def fetchrow(self, sql, *args):
            if 'auction_operations' in sql:
                looked_up.append(args[-1])
                return dict(request_hash=engine.fingerprint('maximum', UUID(AUCTION), command),
                            organization_id=None, outcome=receipt)
            assert 'FOR UPDATE' not in sql
            return lot

    @asynccontextmanager
    async def transaction(pool):
        yield Transaction()

    async def principal(request):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=UUID(OWNER), organization_id=None),
                               roles=['buyer'], organizations=organizations)

    monkeypatch.setattr(engine, 'unit_of_work', transaction)
    application = app()
    application.include_router(proxy.load('routes.py:router'))
    application.state.auction = engine.AuctionEngine(SimpleNamespace(principal=principal))
    async def read_current(request, auction):
        return dict(schema_version=2, auction_id=str(auction), actor_id=OWNER, watch_id=OTHER,
                    revision=3, amount_minor=None, active=False, standing=None)

    application.state.proxy_private_v2 = SimpleNamespace(read_current=read_current)
    application.state.pool = None

    @application.exception_handler(AccessDenied)
    async def denied(request, error):
        return JSONResponse({}, status_code=403)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://auction') as client:
        path = f'/v1/auctions/{AUCTION}/maximum'
        headers = {'Idempotency-Key': 'test-earlier'}
        body = command.model_dump(mode='json')
        assert (await client.post(path, headers=headers, json=body)).json() == receipt

        organizations.append(seller_business)
        blocked = await client.post(path, headers=headers, json=body)
        assert blocked.status_code == 403
        assert 'bid_accepted' not in blocked.text
        assert looked_up == ['test-earlier']

        organizations.clear()
        assert (await client.post(path, headers=headers, json=body)).json() == receipt
    assert looked_up == ['test-earlier', 'test-earlier']


NOTICE_CASES = json.loads((ROOT / 'packages/contracts-auction/proxy/fixtures/notices.v2.json').read_text())


@pytest.mark.parametrize(
    'case', NOTICE_CASES, ids=lambda case: f"{case['kind']}-{case['challenge_minor']}",
)
def test_staged_v2_hook_matches_canonical_event_and_notice_facts(case):
    from bt_contracts.auction.core.models import BidAcceptedEventData
    from bt_contracts.auction.proxy.notices import accepted_bid_notices

    accepted = BidAcceptedEventData.model_validate(case['event'])
    event = accepted.model_dump(mode='json')
    state = dict(opening_minor=400000, current_minor=case['prior_minor'],
                 leader_id=OWNER, sequence=2, increment_bands=[dict(from_minor=0, step_minor=10000)],
                 maxima=[dict(bidder_id=OWNER, amount_minor=450000, sequence=1, active=True)])
    command = dict(kind=case['kind'], bidder_id=OTHER, amount_minor=case['challenge_minor'], sequence=3)
    result = proxy.load(proxy.hooks['auction.proxy.v2'])(state, command)
    assert event['previous_leader_id'] == state['leader_id']
    assert event['bidder_id'] == command['bidder_id']
    assert event['sequence'] == state['sequence'] + len(result['bids'])
    assert event['current_minor'] == result['current_minor']
    assert event['leader_id'] == result['leader_id']
    notices = accepted_bid_notices(
        bidder_id=accepted.bidder_id,
        previous_leader_id=accepted.previous_leader_id,
        leader_id=accepted.leader_id,
    )
    assert case['notices'] == [
        dict(recipient_id=str(buyer), kind=kind) for buyer, kind in notices
    ]


@pytest.mark.parametrize(('kind', 'amount'), [('manual', 445000), ('manual', 450000), ('maximum', 450000)])
def test_displacement_preserves_the_higher_ceiling_for_canonical_persistence(kind, amount):
    state = dict(opening_minor=400000, current_minor=430000, leader_id=OWNER, sequence=3,
                 increment_bands=[dict(from_minor=0, step_minor=10000)],
                 maxima=[dict(bidder_id=OWNER, amount_minor=450000, sequence=1, active=True)])
    command = dict(kind=kind, bidder_id=OTHER, amount_minor=amount, sequence=4)
    result = proxy.load(proxy.hooks['auction.proxy.v2'])(state, command)
    assert result['leader_id'] == OTHER
    assert result['current_minor'] == amount
    assert result['bids'] == [dict(bidder_id=OTHER, amount_minor=amount, automatic=kind == 'maximum')]
    assert result['maxima'][0] == dict(bidder_id=OWNER, amount_minor=450000, sequence=1, active=False)

    # Regaining the lead with an ordinary bid does not reactivate the ceiling.
    next_state = {**state, **result, 'sequence': 4}
    regain = dict(kind='manual', bidder_id=OWNER, amount_minor=amount + 10000, sequence=5)
    regained = proxy.load(proxy.hooks['auction.proxy.v2'])(next_state, regain)
    assert regained['leader_id'] == OWNER
    assert regained['maxima'][0] == result['maxima'][0]


@pytest.mark.asyncio
async def test_registered_v2_maximum_fails_closed_without_current_authority():
    from bt_runtime.app.main import create_app
    from bt_runtime.app.settings import Settings

    route_app = create_app(Settings(service_name='auction', database_url='postgresql://unused/unused',
                                    modules_path=ROOT / 'services/auction/modules/proxy'))
    async def current():
        return SimpleNamespace(subject=OWNER)

    route_app.dependency_overrides[require_principal] = current
    calls = []

    async def submit(request, auction, command, *, kind):
        calls.append((auction, request.headers['Idempotency-Key'], command, kind))
        return dict(status='succeeded', current_minor=400000, revision=3)

    route_app.state.auction = SimpleNamespace(submit=submit)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=route_app),
                                 base_url='http://auction') as client:
        response = await client.post(
            f'/v1/auctions/{AUCTION}/maximum', headers={'Idempotency-Key': OTHER},
            json=dict(action='submit_v2', command=dict(amount_minor=450000, fee_quote_id=OTHER,
                       expected_revision=2, watch_id=OTHER, quote_revision=1, policy_revision='test-policy')),
        )
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'unavailable'
    assert '450000' not in response.text
    assert not calls



@pytest.mark.asyncio
async def test_registered_maximum_does_not_fall_back_after_current_provider_registration():
    from bt_runtime.app.main import create_app
    from bt_runtime.app.settings import Settings

    route_app = create_app(Settings(service_name='auction', database_url='postgresql://unused/unused',
                                    modules_path=ROOT / 'services/auction/modules/proxy'))
    async def current():
        return SimpleNamespace(subject=OWNER)

    route_app.dependency_overrides[require_principal] = current

    calls = []

    async def submit(request, auction_id, command, *, kind):
        calls.append((str(auction_id), request.headers['Idempotency-Key'], command.amount_minor, kind))
        return dict(status='succeeded', current_minor=400000)

    route_app.state.auction = SimpleNamespace(submit=submit)
    route_app.state.proxy_private_v2 = SimpleNamespace()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=route_app),
                                 base_url='http://auction') as client:
        response = await client.post(
            f'/v1/auctions/{AUCTION}/maximum', headers={'Idempotency-Key': 'test-original'},
            json=dict(amount_minor=450000, fee_quote_id=OTHER, expected_revision=2),
        )
    assert response.status_code == 503
    assert response.headers['cache-control'] == 'no-store'
    assert not calls
    assert '450000' not in response.text


@pytest.mark.asyncio
async def test_registered_maximum_never_falls_back_after_canonical_activation():
    from bt_runtime.app.main import create_app
    from bt_runtime.app.settings import Settings

    application = create_app(Settings(service_name='auction', database_url='postgresql://unused/unused',
                                      modules_path=ROOT / 'services/auction/modules/proxy'))
    async def current():
        return SimpleNamespace(subject=OWNER)

    application.dependency_overrides[require_principal] = current
    calls = []
    receipt = dict(status='succeeded', current_minor=400000, revision=3)

    async def submit(request, auction_id, command, *, kind):
        calls.append((request.headers['Idempotency-Key'], auction_id, command.model_dump(mode='json'), kind))
        return receipt

    application.state.auction = SimpleNamespace(submit=submit, bid_admission_version='auction.proxy.v2')
    body = dict(amount_minor=450000, fee_quote_id=OTHER, expected_revision=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://auction') as client:
        response = await client.post(f'/v1/auctions/{AUCTION}/maximum', json=body,
                                     headers={'Idempotency-Key': 'test-legacy-maximum'})

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'unavailable'
    assert not calls


@pytest.mark.asyncio
async def test_cutover_preserves_legacy_receipts_and_fences_delayed_commands(monkeypatch):
    from contextlib import asynccontextmanager

    from fastapi import HTTPException
    from service_app import engine

    route_app = app()
    route_app.include_router(proxy.load('routes.py:router'))

    from fastapi.responses import JSONResponse

    from bt_contracts_core.errors import PublicError

    @route_app.exception_handler(PublicError)
    async def public_error(request, error):
        if error.status != 503:
            raise error
        return JSONResponse({'error': {'code': error.code}}, status_code=503)

    @route_app.exception_handler(AccessDenied)
    async def denied(request, error):
        return JSONResponse({}, status_code=403)

    route_app.state.pool = None
    body = dict(amount_minor=450000, fee_quote_id=OTHER, expected_revision=2)
    command = proxy.load('private.py:MaximumCommand').model_validate(body)
    digest = engine.fingerprint('maximum', UUID(AUCTION), command)
    receipt = dict(operation_id=OTHER, auction_id=AUCTION, status='succeeded', code='bid_accepted', revision=3)
    pending_receipt = dict(receipt, status='pending', code='first_bid_fenced_bid_not_confirmed',
                           commitment_status='succeeded', accepted_sequence=0, current_minor=0,
                           next_minimum_minor=400000, end_version=1,
                           ends_at='2030-01-02T00:00:00Z', server_time='2030-01-02T00:00:00Z')
    records = {
        'test-original': (digest, receipt),
        'test-manual': (engine.fingerprint('manual', UUID(AUCTION), command), receipt),
        'test-fenced-pending': (digest, pending_receipt),
    }
    access = 200
    selling_business = UUID(AUCTION)
    organizations = []
    lock_keys = []
    read_revision, read_watch = 3, OTHER

    async def read(request, auction):
        if access != 200:
            raise HTTPException(access)
        return dict(schema_version=2, auction_id=AUCTION, actor_id=OWNER, watch_id=read_watch,
                    revision=read_revision, amount_minor=None, active=False, standing=None)

    class Transaction:
        async def execute(self, sql, *args):
            if 'pg_advisory_xact_lock' in sql:
                lock_keys.append(args[0])
                return
            assert 'INSERT INTO auction_operations' in sql
            _, subject, organization, key, request_digest, auction, outcome = args
            assert subject == UUID(OWNER) and organization is None and auction == UUID(AUCTION)
            assert lock_keys[-1] == f'operation:{OWNER}:{key}'
            assert key not in records
            records[key] = request_digest, json.loads(outcome)

        async def fetchrow(self, sql, *args):
            if 'auction_lots' in sql:
                return dict(revision=3, watch_id=UUID(OTHER), seller_id=UUID(OTHER), seller_organization_id=selling_business)
            assert args[0] == UUID(OWNER)
            key = args[-1]
            if len(args) == 3:
                assert args[1] == UUID(AUCTION)
            else:
                assert lock_keys[-1] == f'operation:{OWNER}:{key}'
            saved = records.get(key)
            if saved:
                return dict(request_hash=saved[0], organization_id=None, outcome=saved[1])

    @asynccontextmanager
    async def transaction(pool):
        yield Transaction()

    async def current(request):
        if access != 200:
            raise HTTPException(access)
        return SimpleNamespace(roles=['buyer'], organizations=organizations,
                               actor=SimpleNamespace(subject_id=UUID(OWNER), organization_id=None))

    monkeypatch.setattr(engine, 'unit_of_work', transaction)
    admission = engine.AuctionEngine(SimpleNamespace(principal=current))
    admission.bid_admission_version = None
    fresh = []

    async def submit(*args, **kwargs):
        pytest.fail('A maximum must never enter the legacy transaction through this route')

    monkeypatch.setattr(admission, 'submit', submit)
    route_app.state.auction = admission
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=route_app), base_url='http://auction') as client:
        path = f'/v1/auctions/{AUCTION}/maximum'

        async def lookup(key, original=body):
            return await client.post(path, json=dict(action='lookup_v1', operation_key=key, command=original))

        async def replay(key, original=body, *, unwrapped=False):
            payload = original if unwrapped else dict(action='recover_v1', command=original)
            return await client.post(path, headers={'Idempotency-Key': key}, json=payload)

        assert (await lookup('test-original')).json() == receipt
        assert (await lookup('test-manual')).status_code == 404
        assert (await lookup('test-original', dict(body, amount_minor=460000))).status_code == 404
        assert (await client.post(path, json=dict(action='lookup_v1', operation_key='test-original'))).status_code == 422
        assert (await lookup('test-delayed')).status_code == 404
        assert (await lookup('test-fenced-pending')).json() == pending_receipt
        assert (await replay('test-fenced-pending')).json() == pending_receipt
        assert (await replay('test-original')).json() == receipt
        assert (await replay('test-original', unwrapped=True)).json() == receipt
        for malformed in (
            dict(receipt, amount_minor=450000),
            dict(receipt, auction_id=OTHER),
            dict(receipt, revision=body['expected_revision']),
        ):
            records['test-invalid-receipt'] = (digest, malformed)
            response = await lookup('test-invalid-receipt')
            assert response.status_code == 503
            assert '450000' not in response.text
        assert (await replay('test-new', unwrapped=True)).status_code == 503
        assert (await replay('test-new', unwrapped=True)).status_code == 503
        assert (await lookup('test-new')).status_code == 404
        retired_before_activation = await replay('test-retired-before')
        assert retired_before_activation.json()['code'] == 'legacy_maximum_retired'
        assert (await replay('test-retired-before', unwrapped=True)).json() == retired_before_activation.json()
        assert (await lookup('test-retired-before')).json() == retired_before_activation.json()
        assert not fresh

        async def assert_revoked_recovery():
            organizations.append(selling_business)
            try:
                assert (await lookup('test-original')).status_code == 403
                for unwrapped in (False, True):
                    denied_response = await replay('test-original', unwrapped=unwrapped)
                    assert denied_response.status_code == 403
                    assert receipt['operation_id'] not in denied_response.text
            finally:
                organizations.remove(selling_business)
            assert (await replay('test-original')).json() == receipt

        await assert_revoked_recovery()

        async def submit_current(request, auction, incoming):
            raise HTTPException(503)

        route_app.state.proxy_private_v2 = SimpleNamespace(read_current=read, submit_current=submit_current)
        private_read = await client.post(path, json={'action': 'read_v2'})
        assert private_read.json() == dict(schema_version=1, auction_id=AUCTION, actor_id=OWNER, revision=3)
        unavailable = await client.post(
            path,
            headers={'Idempotency-Key': OTHER},
            json=dict(action='submit_v2', command=dict(
                body, watch_id=OTHER, quote_revision=1, policy_revision='test-policy')),
        )
        assert unavailable.status_code == 503
        await assert_revoked_recovery()
        invalid = await replay('test-invalid-receipt', unwrapped=True)
        assert invalid.status_code == 503
        assert '450000' not in invalid.text
        for read_revision, read_watch in ((2, OTHER), (4, OTHER), (3, AUCTION)):
            assert (await lookup('test-original')).status_code == 503
            assert (await replay('test-after-activation', unwrapped=True)).status_code == 503
            assert 'test-after-activation' not in records
        read_revision, read_watch = 3, OTHER
        assert (await replay('test-after-activation', unwrapped=True)).status_code == 503
        assert 'test-after-activation' not in records
        retired = await replay('test-after-activation')
        assert retired.json()['code'] == 'legacy_maximum_retired'
        assert (await replay('test-after-activation', unwrapped=True)).json() == retired.json()
        assert (await replay('test-original', unwrapped=True)).json() == receipt
        assert (await replay('test-original')).json() == receipt
        for access in (403, 503):
            assert (await lookup('test-original')).status_code == access
            assert (await replay('test-delayed')).status_code == access
            assert (await replay('test-delayed', unwrapped=True)).status_code == access
            assert 'test-delayed' not in records
        access = 200
        refused = await replay('test-delayed')
        assert refused.status_code == 200
        assert refused.json()['code'] == 'legacy_maximum_retired'
        assert refused.json()['status'] == 'denied'
        assert '450000' not in refused.text
        assert (await replay('test-delayed')).json() == refused.json()
        assert (await lookup('test-delayed')).json() == refused.json()
        assert records['test-delayed'][0] == digest
        assert not fresh
        with pytest.raises(engine.PublicError, match='idempotency_conflict'):
            await client.post(path, headers={'Idempotency-Key': 'test-delayed'},
                              json=dict(body, amount_minor=460000))

        async def submit_legacy(request, auction, incoming):
            key = request.headers['Idempotency-Key']
            fresh.append(key)
            if key == 'test-without-receipt':
                return receipt
            async with transaction(None) as tx:
                actor = await current(request)
                request_hash = engine.fingerprint('maximum', auction, incoming)
                assert await admission.operation(tx, actor, key, request_hash) is None
                await admission.store(tx, actor, key, request_hash, receipt, auction)
            if key == 'test-lost-reply':
                raise TimeoutError

        route_app.state.proxy_private_v2.submit_legacy_current = submit_legacy
        assert (await replay('test-uncoordinated', unwrapped=True)).status_code == 503
        assert 'test-uncoordinated' not in records
        admission.bid_admission_version = 'auction.proxy.v2'
        assert (await client.post(path, json={'action': 'read_v2'})).json()['schema_version'] == 1
        assert (await replay('test-missing-lookup', unwrapped=True)).status_code == 503
        route_app.state.proxy_private_v2.lookup_current = unused_provider_operation
        assert (await client.post(path, json={'action': 'read_v2'})).json()['schema_version'] == 2

        reconciliations = []
        terminal = dict(pending_receipt, status='denied', code='auction_ended')

        async def reconcile_legacy(request, auction, incoming):
            key = request.headers['Idempotency-Key']
            actor = await current(request)
            assert key == 'test-fenced-pending' and auction == UUID(AUCTION)
            assert engine.fingerprint('maximum', auction, incoming) == digest
            async with transaction(None) as tx:
                assert await admission.operation(tx, actor, key, digest) == pending_receipt
                records[key] = digest, terminal
            reconciliations.append(key)
            # Losing the callback response does not lose the durable decision.
            raise TimeoutError

        route_app.state.proxy_private_v2.reconcile_legacy_current = reconcile_legacy
        assert (await lookup('test-fenced-pending')).json() == pending_receipt
        assert not reconciliations
        organizations.append(selling_business)
        assert (await replay('test-fenced-pending')).status_code == 403
        organizations.clear()
        assert not reconciliations
        assert (await replay('test-fenced-pending')).status_code == 503
        assert (await replay('test-fenced-pending', unwrapped=True)).json() == terminal
        assert (await replay('test-fenced-pending')).json() == terminal
        assert (await lookup('test-fenced-pending')).json() == terminal
        assert reconciliations == ['test-fenced-pending']

        assert (await replay('test-without-receipt', unwrapped=True)).status_code == 503
        assert (await replay('test-new-current', unwrapped=True)).json() == receipt
        assert (await replay('test-new-current', unwrapped=True)).json() == receipt
        assert (await lookup('test-new-current')).json() == receipt
        assert (await replay('test-delayed', unwrapped=True)).json() == refused.json()
        assert (await replay('test-lost-reply', unwrapped=True)).status_code == 503
        assert (await replay('test-lost-reply', unwrapped=True)).json() == receipt
        assert fresh == ['test-without-receipt', 'test-new-current', 'test-lost-reply']


@pytest.mark.asyncio
@pytest.mark.parametrize('installed', ['absent', 'partial', 'current'])
async def test_private_operation_transport_fails_closed_for_missing_methods(installed):
    fixture = ROOT / 'packages/contracts-auction/proxy/fixtures/operations.v2.json'
    case = json.loads(fixture.read_text())[0]

    async def read(request, auction):
        return dict(schema_version=2, auction_id=str(auction), watch_id=case['watch_id'],
                    actor_id=OWNER, revision=3, amount_minor=None, active=False, standing=None)

    async def lookup(request, auction, operation_id):
        assert str(auction) == case['subject_id'] and str(operation_id) == case['operation_id']
        return dict(case, actor_id=OWNER)

    provider = None if installed == 'absent' else (SimpleNamespace() if installed == 'partial' else
               SimpleNamespace(read_current=read, lookup_current=lookup, submit_current=unused_provider_operation))
    application = app(provider)
    application.include_router(proxy.load('routes.py:router'))
    responses = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://auction') as client:
        direct = f"/v2/auctions/{case['subject_id']}/maximum"
        registered = f"/v1/auctions/{case['subject_id']}/maximum"
        responses.append(await client.get(direct))
        responses.append(await client.get(direct + f"/operations/{case['operation_id']}"))
        responses.append(await client.post(registered, json={'action': 'read_v2'}))
        responses.append(await client.post(registered, json={'action': 'lookup_v2', 'operation_id': case['operation_id']}))
    assert [response.status_code for response in responses] == [200 if installed == 'current' else 503] * 4
    if installed == 'current':
        assert responses[0].json() == responses[2].json()
        assert responses[1].json() == responses[3].json()


@pytest.mark.asyncio
async def test_private_provider_alone_cannot_cut_over_fresh_admission():
    async def submit(*args):
        pytest.fail('The current provider cannot submit before canonical activation')

    application = app(SimpleNamespace(submit_current=submit))
    del application.state.auction
    case = json.loads((ROOT / 'packages/contracts-auction/proxy/fixtures/operations.v2.json').read_text())[0]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://auction') as client:
        response = await client.post(
            f"/v2/auctions/{case['subject_id']}/maximum", json=command_body(case),
            headers={'Idempotency-Key': case['operation_id']},
        )
    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize('items,total,next_cursor', [
    ([], 1000, None),
    ([row()], 1, 'test-extra-page'),
    ([row(), row(4)], 1, None),
])
async def test_later_activity_page_rejects_locally_inconsistent_bounds(items, total, next_cursor):
    source = Source(dict(items=items, total=total, next_cursor=next_cursor))
    page = await compose(UUID(OWNER), 'synthetic-token', 'read-1', source, view='leading', cursor='test-page')
    assert page == dict(schema_version=2, state='unavailable', items=[], total=None, next_cursor=None)

@pytest.mark.asyncio
@pytest.mark.parametrize('auction_status', [403, 503])
async def test_reservation_route_checks_orders_independently(monkeypatch, auction_status):
    auction = Source({}, auction_status)
    reservation_id = str(UUID(int=6))
    orders = Source(dict(items=[dict(reservation_id=reservation_id, listing_id=AUCTION,
                                    buyer_id=OWNER, state='awaiting_payment', total_minor=515000,
                                    currency='USD', revision=2, expires_at='2030-01-02T00:00:00Z',
                                    is_demo=True)]))
    application = activity_app(monkeypatch, auction)
    application.state.l06_workspace_clients['orders'] = orders
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        activity = await client.get('/v1/buyer-workspace?view=leading')
        if auction_status == 403:
            assert activity.status_code == 403
            assert activity.json()['error']['code'] == 'auction_access_denied'
        else:
            assert activity.json()['state'] == 'unavailable'
        calls = list(auction.paths)
        reservations = await client.get('/v1/buyer-workspace?section=reservations')
        assert auction.paths == calls
    assert orders.paths == ['/v1/me/reservations?limit=100']
    assert reservations.status_code == 200
    assert reservations.headers['cache-control'] == 'no-store'
    row = reservations.json()['items'][0]
    assert row['reservation_id'] == reservation_id
    assert 'buyer_id' not in row


@pytest.mark.asyncio
@pytest.mark.parametrize('title,valid', [
    ('ساعة Auction ⌚✨ ' * 12, True),
    (None, True),
    ('⌚' * 241, False),
    ({'private_evidence': 'synthetic-evidence'}, False),
])
async def test_bid_title_is_optional_bounded_public_text(title, valid):
    source = Source(dict(items=[dict(row(), listing_title=title)], total=1))
    page = await compose(UUID(OWNER), 'synthetic-token', 'read-title', source, view='leading')
    if valid:
        assert page['state'] == 'available'
        assert page['items'][0]['listing_title'] == title
        assert 'buyer_id' not in page['items'][0]
    else:
        assert page == dict(schema_version=2, state='unavailable', items=[], total=None, next_cursor=None)


@pytest.mark.asyncio
async def test_earlier_receipts_are_discoverable_without_request_details(monkeypatch):
    from contextlib import asynccontextmanager
    from service_app import engine

    application = app()
    application.include_router(proxy.load('routes.py:router'))
    actor_id, auction_id = UUID(OWNER), UUID(AUCTION)
    with sqlite3.connect(':memory:') as database:
        database.row_factory = sqlite3.Row
        database.execute(
            'CREATE TABLE auction_operations(id TEXT, created_at TEXT, outcome TEXT, '
            'auction_id TEXT, subject_id TEXT, organization_id TEXT)'
        )
        accepted = dict(status='succeeded', code='bid_accepted', accepted_sequence=1)
        stale = dict(status='denied', code='stale_revision', accepted_sequence=1)
        expected = [str(UUID(int=index)) for index in range(1, 23)]
        inserts = [(reference, AUCTION, OWNER, None, accepted if index else stale)
                   for index, reference in enumerate(expected)]
        inserts += [(OTHER, auction, owner, business, outcome) for auction, owner, business, outcome in [
            (AUCTION, OTHER, None, accepted),
            (AUCTION, OWNER, OTHER, accepted),
            (OTHER, OWNER, None, accepted),
            (AUCTION, OWNER, None, dict(status='succeeded', code='auction_opened')),
        ]]
        database.executemany('INSERT INTO auction_operations VALUES (?, ?, ?, ?, ?, ?)', [
            (reference, '2030-01-01T12:00:00Z', json.dumps(outcome), auction, actor, business)
            for reference, auction, actor, business, outcome in inserts
        ])

        class Transaction:
            async def fetchrow(self, sql, auction):
                assert auction == auction_id
                return dict(revision=3, watch_id=UUID(OTHER), seller_id=UUID(OTHER), seller_organization_id=None)

            async def fetch(self, sql, auction, actor, cursor):
                assert (auction, actor) == (auction_id, actor_id)
                sql = sql.replace('::uuid', '')
                for position in (1, 2, 3):
                    sql = sql.replace(f'${position}', f'?{position}')
                return database.execute(sql, (str(auction), str(actor), str(cursor) if cursor else None)).fetchall()

        @asynccontextmanager
        async def transaction(pool):
            yield Transaction()

        async def principal(request):
            return SimpleNamespace(roles=['buyer'], organizations=[],
                                   actor=SimpleNamespace(subject_id=actor_id, organization_id=None))

        async def revoked(*args):
            from fastapi import HTTPException
            raise HTTPException(403)

        monkeypatch.setattr(engine, 'unit_of_work', transaction)
        application.state.pool = None
        application.state.auction = SimpleNamespace(dependencies=SimpleNamespace(principal=principal))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                     base_url='http://auction') as client:
            path = f'/v1/auctions/{AUCTION}/maximum'
            action = dict(action='list_bid_receipts_v1')
            first = await client.post(path, json=action)
            assert first.status_code == 200 and first.headers['cache-control'] == 'no-store'
            body = first.json()
            assert [item['operation_id'] for item in body['items']] == expected[:1:-1]
            assert set(body['items'][0]) == {'operation_id', 'recorded_at', 'state'}
            second = await client.post(path, json=dict(action, before=body['next_cursor']))
            assert [item['state'] for item in second.json()['items']] == ['accepted', 'stale']
            assert (await client.post(path, json=dict(action, before=OTHER))).status_code == 409
            application.state.proxy_private_v2 = SimpleNamespace(read_current=revoked)
            assert (await client.post(path, json=action)).status_code == 403


@pytest.mark.asyncio
async def test_reservations_keep_legacy_currency_out_of_checkout(monkeypatch):
    row = dict(reservation_id=OTHER, listing_id=AUCTION, buyer_id=OWNER, state='awaiting_payment',
               total_minor=515000, currency='USD', revision=2, expires_at='2030-01-02T00:00:00Z', is_demo=True)
    legacy = dict(row, currency='LBP', reservation_id=AUCTION)
    orders = Source(dict(items=[row, legacy], next_cursor=legacy['reservation_id']))
    application = activity_app(monkeypatch, Source({}, 404))
    application.state.l06_workspace_clients['orders'] = orders
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        for suffix in ('?section=reservations', ''):
            response = await client.get('/v1/buyer-workspace' + suffix)
            assert response.status_code == 200
            result = response.json()
            section = result.get('reservations', result)
            assert [item['reservation_id'] for item in section['items']] == [OTHER]
            assert section['next_cursor'] == legacy['reservation_id']
    assert orders.body['items'][-1] == legacy


@pytest.mark.asyncio
async def test_reservation_route_follows_orders_cursor_across_filtered_page(monkeypatch):
    reservations = [
        dict(reservation_id=str(UUID(int=1000 + i)), listing_id=AUCTION, buyer_id=OWNER,
             state='awaiting_payment', total_minor=515000, currency='USD' if i >= 100 else 'LBP',
             revision=2, expires_at='2030-01-02T00:00:00Z', is_demo=True)
        for i in range(101)
    ]
    boundary = reservations[99]['reservation_id']
    paths = []

    class Orders:
        async def request(self, method, path, headers):
            assert method == 'GET'
            paths.append(path)
            params = parse_qs(urlsplit(path).query)
            assert params['limit'] == ['100']
            if 'cursor' in params:
                assert params['cursor'] == [boundary]
                return httpx.Response(200, json=dict(items=reservations[100:], next_cursor=None))
            return httpx.Response(200, json=dict(items=reservations[:100], next_cursor=boundary))

    application = activity_app(monkeypatch, Source({}, 503))
    application.state.l06_workspace_clients['orders'] = Orders()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                 base_url='http://communications',
                                 headers={'Authorization': 'Bearer synthetic-token'}) as client:
        path = '/v1/buyer-workspace'
        first = await client.get(path, params={'section': 'reservations'})
        assert first.json() == dict(state='available', items=[], next_cursor=boundary)
        second = await client.get(path, params={'section': 'reservations', 'cursor': first.json()['next_cursor']})
        assert second.status_code == 200
        assert second.headers['cache-control'] == 'no-store'
        assert second.json()['next_cursor'] is None
        assert [row['reservation_id'] for row in second.json()['items']] == [reservations[-1]['reservation_id']]
        invalid = await client.get(path, params={'section': 'reservations', 'cursor': 'invalid'})
        assert invalid.status_code == 422
    assert len(paths) == 2
