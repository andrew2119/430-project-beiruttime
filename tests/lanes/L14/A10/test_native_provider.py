"""Native request, process ownership and fail-closed report checks."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest

from contract import CASES, Dataset
from native_provider import MissingCapability, NativeProvider, Replica, local_url, private_json
from run_native import SCENARIOS, execute


@pytest.mark.parametrize('error,elapsed', [(False, 10), (True, 10), (False, 30001)])
def test_immediately_beaten_challenger_requires_durable_notice(error, elapsed):
    from contract import Sample

    class ContinuedJourney(Exception):
        pass

    provider = NativeProvider(None, {}, None, None)
    lot = {'id': 'test-auction', 'current_minor': 400000}
    receipt = {'status': 'succeeded', 'current_minor': 430000, 'accepted_sequence': 2}
    provider.snapshot = AsyncMock(side_effect=[lot, lot, ContinuedJourney()])
    provider.command = AsyncMock(return_value={'amount_minor': 420000})
    provider.request = AsyncMock(return_value={'status': 'succeeded'})
    provider.submit = AsyncMock(return_value=receipt)
    provider.observe_notice = AsyncMock(return_value=Sample(1, 0, 2, elapsed, error))
    expected = AssertionError if error or elapsed > 30000 else ContinuedJourney
    with pytest.raises(expected):
        asyncio.run(provider.maximum_journey(lot))
    observation = provider.observe_notice.await_args
    assert observation.args[:3] == (lot, 1, receipt)
    assert isinstance(observation.args[3], float)
    assert provider.submit.await_count == 1
    assert provider.snapshot.await_count == (2 if expected is AssertionError else 3)


def test_request_retries_preserve_command_and_reference():
    requests = []
    async def handle(request):
        requests.append(request)
        if len(requests) < 3:
            raise httpx.ReadTimeout('test timeout')
        return httpx.Response(200, json={'status': 'pending'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = NativeProvider(None, {}, None, client)
            provider.tokens[0] = 'test-token'
            provider.session_deadlines[0] = float('inf')
            result = await provider.request('auction', 'POST', '/v1/test', actor=0,
                                            body={'amount_minor': 100}, key='test-operation')
            assert result['status'] == 'pending'
    asyncio.run(scenario())
    assert len(requests) == 3
    assert len({r.headers['Idempotency-Key'] for r in requests}) == 1
    assert len({r.content for r in requests}) == 1
    assert all(r.url.host == '127.0.0.1' for r in requests)


@pytest.mark.parametrize('value', ['https://example.test', 'http://localhost:8103',
                                   'http://127.0.0.1.example.test', 'file:///tmp/test'])
def test_external_provider_configuration_refused(value):
    with pytest.raises(MissingCapability):
        local_url(value)


def test_private_configuration_permissions(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{}')
    path.chmod(0o644)
    with pytest.raises(MissingCapability):
        private_json(path)
    path.chmod(0o600)
    assert private_json(path) == {}


@pytest.mark.parametrize('key', [
    'BT_DATABASE_OWNER_URL', 'BT_MIGRATION_DATABASE_URL', 'BT_TEST_DATABASE_READ_URL',
    'TEST_RUNTIME_URL', 'TEST_DATABASE_ADMIN_URL', 'OWNER_URL'])
@pytest.mark.parametrize('value', [
    'postgresql://test-owner:test-password@127.0.0.1:54329/test',
    'http://127.0.0.1:54329/test',
    'postgresql://test-owner:test-password@example.test:54329/test',
    'postgresql://test-owner:test-password@127.0.0.1:5432/test'])
def test_replica_database_manifest_urls(tmp_path, monkeypatch, key, value):
    socket = MagicMock()
    socket.return_value.__enter__.return_value.getsockname.return_value = ('127.0.0.1', 8104)
    monkeypatch.setattr('native_provider.socket.socket', socket)
    database_url = 'postgresql://test-runtime:test-password@127.0.0.1:54329/test'
    configured = {'BT_DATABASE_URL': database_url, key: value,
                  'BT_SERVICE_URL': 'http://127.0.0.1:8103'}
    path = tmp_path / 'native-v1.json'
    path.write_text(json.dumps({'schema_version': 1, 'services': {
        'auction': {'env': configured}}}))
    path.chmod(0o600)
    (tmp_path / 'domain-contracts' / 'bt_contracts').mkdir(parents=True)
    replica = Replica(tmp_path)
    assert replica.env['BT_DATABASE_URL'] == database_url
    assert key not in replica.env
    assert replica.env['BT_SERVICE_URL'] == configured['BT_SERVICE_URL']


def test_missing_setup_writes_every_named_failure(tmp_path):
    assert asyncio.run(execute(tmp_path)) == 1
    result = json.loads((tmp_path / 'scenarios/a10/summary.json').read_text())
    assert result['status'] == 'failed'
    assert set(result['scenarios']) == {'viewers', 'bidders', 'notices', *CASES}
    assert all(row['state'] == 'failed' and row['missing_capability']
               and row['operation_ids'] == [] for row in result['scenarios'].values())


def test_missing_notice_observations_cannot_be_reported_as_latency():
    provider = NativeProvider(None, {}, None, None)
    with pytest.raises(MissingCapability, match='complete_bid_notice_observations'):
        asyncio.run(provider.run_load('notices', Dataset()))


def test_history_rejects_gap_and_stalled_cursor():
    provider = NativeProvider(None, {}, None, None)
    provider.request = AsyncMock(return_value={'items': [{'sequence': 2}], 'has_more': False})
    with pytest.raises(AssertionError, match='gap free'):
        asyncio.run(provider.history('test-lot', 0))


def test_viewer_coverage_is_concurrent_and_measured():
    provider = NativeProvider(None, {}, None, None)
    provider.lot = AsyncMock(return_value={'id': 'test-lot'})
    provider.command = AsyncMock(return_value={})
    provider.submit = AsyncMock(return_value={'status': 'succeeded', 'accepted_sequence': 7})
    active = peak = 0
    async def snapshot(identifier, replica=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.001)
        active -= 1
        return {'accepted_sequence': 7}
    provider.snapshot = snapshot
    async def request(*args, **kwargs):
        assert kwargs['actor'] in range(50)
        return await snapshot('test-lot')
    provider.request = request
    rows = asyncio.run(provider.run_load('viewers', Dataset()))
    assert len(rows) == 100 and peak == 100
    assert {(r.participant, r.replica) for r in rows} == {
        (p, r) for p in range(50) for r in range(2)}
    assert all(r.sequence == 7 and r.elapsed_ms > 0 and not r.error for r in rows)


def test_owned_replica_stop_reaps_only_its_child():
    from unittest.mock import Mock
    from native_provider import Replica
    replica = object.__new__(Replica)
    child = Mock()
    child.poll.side_effect = [None, -9]
    replica.process = child
    asyncio.run(replica.stop())
    child.kill.assert_called_once_with()
    child.wait.assert_called_once_with(timeout=0)
    assert replica.process is None
    asyncio.run(replica.stop())
    child.kill.assert_called_once()


def test_stale_http_denial_keeps_public_code():
    provider = NativeProvider(None, {}, None, None)
    provider.request = AsyncMock(return_value={'error': {'code': 'stale_revision'}})
    result = asyncio.run(provider.submit({'id': 'test-lot'}, 0, {}, 'test-key'))
    assert result == {'status': 'denied', 'code': 'stale_revision'}
    assert not provider.operations


def test_bidder_rebinds_only_after_stale_denial_and_restarts_mid_load():
    from unittest.mock import Mock
    replica = Mock(restart=AsyncMock())
    provider = NativeProvider(None, {}, replica, None)
    provider.lot = AsyncMock(return_value={'id': 'test-lot'})
    provider.snapshot = AsyncMock(return_value={'id': 'test-lot', 'revision': 2})
    provider.command = AsyncMock(return_value={'expected_revision': 2})
    calls = []
    async def submit(lot, actor, body, key, replica=None):
        calls.append((actor, key))
        assert replica == (1 if actor % 2 else None)
        if len(calls) == 1:
            return {'status': 'denied', 'code': 'stale_revision'}
        return {'status': 'succeeded', 'accepted_sequence': len(calls) - 1}
    provider.submit = submit
    async def lookup(*args, **kwargs):
        return {'status': 'succeeded', 'accepted_sequence': len(calls) - 1}
    provider.request = lookup
    from contract import Sample
    provider.observe_notice = AsyncMock(return_value=Sample(0, 0, 1, 1))
    rows = asyncio.run(provider.run_load('bidders', Dataset(bidders=2)))
    assert len(rows) == 2 and all(not row.error for row in rows)
    assert len({key for _, key in calls}) == 3
    assert provider.snapshot.await_count == 3
    replica.restart.assert_awaited_once()


def test_recovery_checks_load_receipts_history_and_winner():
    from unittest.mock import Mock
    replica = Mock(restart=AsyncMock())
    provider = NativeProvider(None, {}, replica, None)
    provider.lots['bidders'] = {'id': 'test-lot'}
    receipt = {'status': 'succeeded', 'accepted_sequence': 1}
    provider.acknowledged = [(0, 'test-key', receipt)]
    provider.owned_acknowledged = list(provider.acknowledged)
    provider.mid_load_restarted = True
    provider.snapshot = AsyncMock(return_value={'accepted_sequence': 1})
    provider.load_allocation = AsyncMock(return_value=('test-order', 'test-watch'))
    provider.history = AsyncMock(return_value=[{
        'sequence': 1, 'bidder': 'Bidder test', 'amount_minor': 400000}])
    winner = {'winner': 'Bidder test', 'closing_minor': 400000, 'status': 'closed'}
    async def request(service, method, path, **kwargs):
        return receipt if 'by-key' in path else winner
    provider.request = AsyncMock(side_effect=request)
    result = asyncio.run(provider.exercise('worker_restart_acknowledged_bids', Dataset(bidders=1)))
    assert result.invariants == ('all_acknowledged_retained', 'same_sequence')
    replica.restart.assert_awaited_once()
    assert provider.load_allocation.await_count == 2
    assert provider.snapshot.await_count == 2
    assert provider.history.await_count == 4


def prepared_input(run_dir):
    emails = ['seller@example.test', *(f'buyer{i}@example.test' for i in range(200))]
    inputs = {
        'seller': {'email': emails[0], 'password': 'test-password'},
        'actors': [{'email': email, 'password': 'test-password'} for email in emails[1:]],
        'sessions': {email: {'subject_id': str(UUID(int=i + 1)),
                             'refresh_cookie': f'test-cookie-{i}'}
                     for i, email in enumerate(emails)},
        'listings': {'viewers': 'test-listing'},
    }
    path = run_dir / 'a10-input.json'
    path.touch(mode=0o600)
    path.write_text(json.dumps(inputs))
    return path, emails


def test_preparation_consumes_all_prepared_sessions(tmp_path):
    path, emails = prepared_input(tmp_path)
    refreshes, accounts, contacts = [], [], []

    def handle(request):
        endpoint = request.url.path
        if endpoint.endswith('/refresh'):
            index = len(refreshes)
            assert request.headers['Cookie'] == f'bt_refresh=test-cookie-{index}'
            assert private_json(path)['sessions'][emails[index]]['refresh_cookie'] is None
            refreshes.append(index)
            return httpx.Response(200, json={'access_token': f'test-token-{index}'},
                                  headers={'Set-Cookie': f'bt_refresh=test-next-{index}; Path=/'})
        index = int(request.headers['Authorization'].rsplit('-', 1)[1])
        assert private_json(path)['sessions'][emails[index]]['refresh_cookie'] == f'test-next-{index}'
        if endpoint == '/v1/accounts/me':
            accounts.append(index)
            return httpx.Response(200, json={'id': str(UUID(int=index + 1)), 'email': emails[index]})
        assert endpoint == '/v1/contacts'
        contacts.append(index)
        return httpx.Response(200, json={'email_verified': True})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = NativeProvider(tmp_path, private_json(path), None, client)
            await provider.prepare()
            assert len(provider.subjects) == 201
            assert provider.subjects['seller'] == str(UUID(int=1))
            assert provider.subjects[199] == str(UUID(int=201))

    asyncio.run(scenario())
    assert refreshes == accounts == list(range(201))
    assert contacts == list(range(1, 201))
    assert path.stat().st_mode & 0o777 == 0o600
    assert private_json(path)['listings'] == {'viewers': 'test-listing'}


@pytest.mark.parametrize('failure', ['stale', 'lost_response', 'wrong_subject', 'unverified'])
def test_unusable_prepared_session_has_no_identity_proof(tmp_path, failure):
    path, emails = prepared_input(tmp_path)
    email = emails[1]
    calls = []

    def handle(request):
        endpoint = request.url.path
        calls.append(endpoint)
        if endpoint.endswith('/refresh'):
            if failure == 'stale':
                return httpx.Response(401)
            if failure == 'lost_response':
                raise httpx.ReadError('test response loss')
            return httpx.Response(200, json={'access_token': 'test-renewed-token'},
                                  headers={'Set-Cookie': 'bt_refresh=test-successor; Path=/'})
        if endpoint == '/v1/accounts/me':
            subject = 1 if failure == 'wrong_subject' else 2
            return httpx.Response(200, json={'id': str(UUID(int=subject)), 'email': email})
        assert endpoint == '/v1/contacts'
        return httpx.Response(200, json={'email_verified': False, 'phone_verified': False})

    expected = {'stale': 'identity_http_401', 'lost_response': 'request_transport',
                'wrong_subject': 'prepared_session_identity_mismatch',
                'unverified': 'verified_buyer_contacts'}

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = NativeProvider(tmp_path, private_json(path), None, client)
            provider.session_emails[0] = email
            with pytest.raises(MissingCapability, match=expected[failure]):
                await provider.renew_session(0)
            assert not provider.subjects and not provider.tokens
            if failure in ('stale', 'lost_response'):
                resumed = NativeProvider(tmp_path, private_json(path), None, client)
                resumed.session_emails[0] = email
                with pytest.raises(MissingCapability, match='refresh_session_cookie'):
                    await resumed.renew_session(0)
                assert len(calls) == 1

    asyncio.run(scenario())
    assert calls.count('/api/web/v1/identity/v1/accounts/refresh') == 1
    cookie = private_json(path)['sessions'][email]['refresh_cookie']
    assert cookie == ('test-successor' if failure in ('wrong_subject', 'unverified') else None)


def test_quote_request_uses_current_schedule():
    provider = NativeProvider(None, {}, None, None)
    provider.request = AsyncMock(side_effect=[
        {'id': 'test-quote', 'revision': 1, 'payable_minor': 412000},
        {'reviewed_at': 'test-time'}])
    asyncio.run(provider.command({'id': 'test-lot', 'revision': 2,
                                 'next_minimum_minor': 400000}, 0))
    for call in provider.request.await_args_list:
        assert call.kwargs['body']['schedule_id'] == 'usd-v2'


def test_session_rotation_is_checkpointed_and_serialized(tmp_path, monkeypatch):
    path, emails = prepared_input(tmp_path)
    email = emails[1]
    clock = [100.0]
    monkeypatch.setattr('native_provider.time.monotonic', lambda: clock[0])
    cookies = []

    async def handle(request):
        if request.url.path.endswith('/refresh'):
            cookies.append(request.headers['Cookie'])
            await asyncio.sleep(0)
            return httpx.Response(200, json={'access_token': 'test-renewed-token',
                                            'expires_in': 300},
                                  headers={'Set-Cookie': f'bt_refresh=test-rotation-{len(cookies)}; Path=/'})
        assert request.headers['Authorization'] == 'Bearer test-renewed-token'
        if request.url.path == '/v1/accounts/me':
            return httpx.Response(200, json={'id': str(UUID(int=2)), 'email': email})
        if request.url.path == '/v1/contacts':
            return httpx.Response(200, json={'phone_verified': True})
        return httpx.Response(200, json={})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = NativeProvider(tmp_path, private_json(path), None, client)
            provider.session_emails[0] = email
            await asyncio.gather(*(provider.request('auction', 'GET', '/v1/test', actor=0)
                                   for _ in range(8)))
            assert cookies == ['bt_refresh=test-cookie-1']
            clock[0] += 600
            await provider.request('auction', 'GET', '/v1/test', actor=0)
            resumed = NativeProvider(tmp_path, private_json(path), None, client)
            resumed.session_emails[0] = email
            await resumed.request('auction', 'GET', '/v1/test', actor=0)

    asyncio.run(scenario())
    assert cookies == ['bt_refresh=test-cookie-1', 'bt_refresh=test-rotation-1',
                       'bt_refresh=test-rotation-2']
    assert private_json(path)['sessions'][email]['refresh_cookie'] == 'test-rotation-3'


def test_revocation_consumes_session_after_other_scenarios(tmp_path):
    path, emails = prepared_input(tmp_path)
    email = emails[1]
    calls = []

    def handle(request):
        endpoint = request.url.path
        calls.append(endpoint)
        assert request.headers['Authorization'] == 'Bearer test-verified-token'
        assert private_json(path)['sessions'][email]['refresh_cookie'] is None
        if endpoint.endswith('/logout'):
            assert request.headers['Cookie'] == 'bt_refresh=test-cookie-1'
            return httpx.Response(200, json={'signed_out': True})
        assert endpoint.endswith('/bids')
        return httpx.Response(401, json={})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = NativeProvider(tmp_path, private_json(path), None, client)
            provider.session_emails[0] = email
            provider.tokens[0] = 'test-verified-token'
            provider.session_deadlines[0] = float('inf')
            provider.lot = AsyncMock(return_value={'id': 'test-lot'})
            provider.command = AsyncMock(return_value={'amount_minor': 400000})
            provider.history = AsyncMock(return_value=[])
            result = await provider.exercise('revoked_identity', Dataset(bidders=1))
            assert result.state == 'denied'
            assert provider.history.await_count == 2
            assert 0 not in provider.tokens

    asyncio.run(scenario())
    assert SCENARIOS[-1] == 'revoked_identity'
    assert calls == ['/api/web/v1/identity/v1/accounts/logout',
                     '/api/web/v1/auction/v1/auctions/test-lot/bids']


def test_notice_measurement_requires_bound_recipient_event_and_public_inbox():
    import time
    provider = NativeProvider(None, {}, None, None)
    provider.notice_binding = AsyncMock(return_value=('test-notice', 'test-inbox'))
    notice = {'id': 'test-notice', 'auction_id': 'test-lot',
              'sequence': 3, 'kind': 'bid_accepted'}
    provider.request = AsyncMock(side_effect=[
        {'items': [notice]}, {'notice': notice}, {'items': [{'id': 'test-inbox'}]}])
    row = asyncio.run(provider.observe_notice({'id': 'test-lot'}, 7,
        {'accepted_sequence': 3}, time.monotonic() - .1))
    assert row.participant == 7 and row.sequence == 3 and row.elapsed_ms >= 100
    provider.notice_binding.assert_awaited_once_with({'id': 'test-lot'}, 7, 3)
    assert all(call.kwargs == {'actor': 7} for call in provider.request.await_args_list)
    assert provider.request.await_args_list[-1].args[2] == '/v1/inbox?limit=50'


def test_notice_wrong_event_never_passes(monkeypatch):
    provider = NativeProvider(None, {}, None, None)
    provider.request = AsyncMock(return_value={'items': [{
        'id': 'test-unrelated', 'auction_id': 'test-lot',
        'sequence': 2, 'kind': 'bid_accepted'}]})
    provider.notice_binding = AsyncMock()
    clock = [0]
    def tick():
        clock[0] += 10
        return clock[0]
    monkeypatch.setattr('native_provider.time.monotonic', tick)
    monkeypatch.setattr('native_provider.asyncio.sleep', AsyncMock())
    row = asyncio.run(provider.observe_notice({'id': 'test-lot'}, 7, {'accepted_sequence': 3}, 0))
    assert row.error and row.participant == 7 and row.sequence == 3
    provider.notice_binding.assert_not_awaited()


def test_notice_binding_uses_authenticated_owner_receipts():
    provider = NativeProvider(None, {}, None, None)
    provider.request = AsyncMock(side_effect=[
        {'event_id': 'test-event', 'auction_id': 'test-lot', 'sequence': 3},
        {'event_id': 'test-event', 'auction_id': 'test-lot', 'sequence': 3,
         'notice_id': 'test-notice', 'inbox_id': 'test-inbox'}])
    assert asyncio.run(provider.notice_binding({'id': 'test-lot'}, 7, 3)) == (
        'test-notice', 'test-inbox')
    assert [call.args[2] for call in provider.request.await_args_list] == [
        '/v1/auctions/test-lot/bid-receipts/3', '/v1/bid-notice-receipts/test-event']
    assert all(call.kwargs['actor'] == 7 for call in provider.request.await_args_list)


@pytest.mark.parametrize('receipt', [
    {'error': {'code': 'not_found'}},
    {'event_id': 'test-event', 'auction_id': 'test-lot', 'sequence': 3,
     'notice_id': 'test-notice', 'inbox_id': None}])
def test_notice_binding_waits_for_committed_inbox(receipt):
    provider = NativeProvider(None, {}, None, None)
    provider.request = AsyncMock(side_effect=[{'event_id': 'test-event'}, receipt])
    assert asyncio.run(provider.notice_binding({'id': 'test-lot'}, 7, 3)) is None


@pytest.mark.parametrize('kind,count', [('viewers', 100), ('bidders', 200)])
def test_load_preserves_every_participant_error(kind, count):
    provider = NativeProvider(None, {}, None, None)
    provider.lot = AsyncMock(return_value={'id': 'test-lot'})
    provider.command = AsyncMock(return_value={})
    provider.submit = AsyncMock(return_value={'status': 'succeeded', 'accepted_sequence': 1})
    provider.request = AsyncMock(side_effect=MissingCapability('auction_http_503'))
    provider.snapshot = AsyncMock(side_effect=MissingCapability('request_transport'))
    rows = asyncio.run(provider.run_load(kind, Dataset()))
    assert len(rows) == count and all(row.error for row in rows)
    if kind == 'bidders':
        assert provider.failures == {'request_transport': 200}


def test_post_commit_response_loss_retries_original_command():
    requests = []
    async def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'status': 'succeeded', 'operation_id': 'test-operation'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = NativeProvider(None, {}, None, client)
            return await provider.request('auction', 'POST', '/v1/test',
                key='test-key', body={'amount_minor': 100}, lose_response_once=True)
    assert asyncio.run(scenario())['status'] == 'succeeded'
    assert len(requests) == 2
    assert requests[0].content == requests[1].content
    assert all(request.headers['Idempotency-Key'] == 'test-key' for request in requests)


def test_report_keeps_error_measurements_and_denials(tmp_path, monkeypatch):
    from contract import Sample
    class Process:
        def __init__(self, run_dir):
            pass
        async def start(self):
            pass
        async def stop(self):
            pass
    class Provider:
        def __init__(self, *args):
            self.operations = []
            self.acknowledged = []
            self.failures = {'stale_revision': 3}
        async def prepare(self):
            pass
        async def run_load(self, name, dataset):
            count, replicas = (50, 2) if name == 'viewers' else (200, 1)
            return [Sample(person, replica, 1, 10, person == 0)
                    for person in range(count) for replica in range(replicas)]
        async def exercise(self, name, dataset):
            raise MissingCapability('test_control_unavailable')
    monkeypatch.setattr('run_native.private_json', lambda path: {})
    monkeypatch.setattr('run_native.Replica', Process)
    monkeypatch.setattr('run_native.NativeProvider', Provider)
    assert asyncio.run(execute(tmp_path)) == 1
    report = json.loads((tmp_path / 'scenarios/a10/summary.json').read_text())
    bidders = report['scenarios']['bidders']
    assert bidders['state'] == 'failed'
    assert bidders['business_denials'] == {'stale_revision': 3}
    assert bidders['measurements']['samples'] == 200
    assert bidders['measurements']['errors'] == 1
    assert bidders['measurements']['p50_ms'] == bidders['measurements']['p95_ms'] == 10


def test_owned_writers_remain_concurrent():
    from unittest.mock import Mock
    from contract import Sample
    provider = NativeProvider(None, {}, Mock(restart=AsyncMock()), None)
    provider.lot = AsyncMock(return_value={'id': 'test-lot'})
    provider.snapshot = AsyncMock(return_value={'id': 'test-lot'})
    provider.command = AsyncMock(return_value={})
    active = peak = sequence = 0
    async def submit(lot, actor, body, key, replica=None):
        nonlocal active, peak, sequence
        if replica == 1:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(.001)
        sequence += 1
        if replica == 1:
            active -= 1
        return {'status': 'succeeded', 'accepted_sequence': sequence}
    provider.submit = submit
    provider.observe_notice = AsyncMock(return_value=Sample(0, 0, 1, 1))
    rows = asyncio.run(provider.run_load('bidders', Dataset(bidders=8)))
    assert len(rows) == 8 and all(not row.error for row in rows)
    assert peak > 1
    assert set(provider.acknowledged_processes.values()) == {0, 1}
    assert len(provider.owned_acknowledged) == 4
    provider.replica.restart.assert_awaited_once()


@pytest.mark.parametrize('key,value', [
    ('BT_DATABASE_URL', 'http://127.0.0.1:54329/test'),
    ('BT_DATABASE_URL', 'postgresql://test-runtime:test-password@example.test:54329/test'),
    ('BT_SERVICE_URL', 'postgresql://127.0.0.1:54329/test'),
    ('BT_SERVICE_URL', 'http://example.test:8103')])
def test_retained_native_urls_are_validated(tmp_path, key, value):
    configured = {'BT_DATABASE_URL': 'postgresql://127.0.0.1:54329/test',
                  'BT_SERVICE_URL': 'http://127.0.0.1:8103',
                  'TEST_RUNTIME_URL': 'postgresql://127.0.0.1:54329/test',
                  'TEST_DATABASE_ADMIN_URL': 'postgresql://127.0.0.1:54329/postgres',
                  'OWNER_URL': 'postgresql://127.0.0.1:54329/test'}
    configured[key] = value
    path = tmp_path / 'native-v1.json'
    path.write_text(json.dumps({'schema_version': 1, 'services': {'auction': {'env': configured}}}))
    path.chmod(0o600)
    with pytest.raises(MissingCapability, match='loopback_provider_configuration'):
        Replica(tmp_path)


@pytest.mark.parametrize('case', ['timeout_pending', 'outbox_replay_duplicate_notice',
                                  'one_winner_allocation_restart'])
def test_interrupted_cases_dispatch_with_fresh_stock(case):
    from contract import CaseResult
    provider = NativeProvider(None, {}, None, None)
    lot = {'id': 'test-auction'}
    provider.lot = AsyncMock(return_value=lot)
    expected = CaseResult('pending' if case == 'timeout_pending' else 'succeeded', ())
    provider.interrupted_journey = AsyncMock(return_value=expected)
    assert asyncio.run(provider.exercise(case, Dataset())) == expected
    provider.lot.assert_awaited_once_with(case)
    provider.interrupted_journey.assert_awaited_once_with(case, lot)


@pytest.mark.parametrize('final_operation', ['test-operation', 'test-different-operation'])
def test_pending_control_reconciles_original_operation_and_restores_environment(monkeypatch, final_operation):
    from unittest.mock import Mock
    class Barrier:
        def __init__(self, *args, **kwargs):
            self.url = 'http://127.0.0.1:12345'
            self.committed = asyncio.Event()
            self.committed.set()
            self.release = asyncio.Event()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr('native_provider.ResponseBarrier', Barrier)
    replica = Mock(env={'ORDERS_API_URL': 'http://127.0.0.1:8104'}, restart=AsyncMock())
    provider = NativeProvider(None, {}, replica, None)
    provider.command = AsyncMock(return_value={'amount_minor': 400000})
    provider.request = AsyncMock(side_effect=[{'error': {'code': 'sale_mode_pending'}},
        {'status': 'pending', 'operation_id': 'test-operation', 'accepted_sequence': 0}])
    recovered = {'status': 'succeeded', 'operation_id': final_operation, 'accepted_sequence': 1}
    provider.submit = AsyncMock(return_value=recovered)
    provider.history = AsyncMock(side_effect=[[], [{'sequence': 1}]])
    async def run():
        return await provider.interrupted_journey('timeout_pending', {'id': 'test-auction'})
    if final_operation == 'test-operation':
        assert asyncio.run(run()).state == 'pending'
        calls = provider.submit.await_args_list
        assert len(calls) == 2 and calls[0].args == calls[1].args
    else:
        with pytest.raises(AssertionError):
            asyncio.run(run())
    assert replica.env == {'ORDERS_API_URL': 'http://127.0.0.1:8104'}
    assert replica.restart.await_count == 2


@pytest.mark.parametrize('boundary_code', ['auction_ended', None])
def test_equal_deadline_requires_owner_boundary_and_real_denial(boundary_code):
    lot = {'id': 'test-auction', 'ends_at': '2026-11-17T00:00:00+00:00',
           'revision': 1, 'accepted_sequence': 0, 'current_minor': 0}
    boundary = {'auction_id': lot['id'], 'ends_at': lot['ends_at'],
                'evaluated_at': lot['ends_at'], 'revision': 1,
                'accepted_sequence': 0, 'code': boundary_code}
    provider = NativeProvider(None, {}, None, None)
    provider.lot = AsyncMock(return_value=lot)
    provider.command = AsyncMock(return_value={'amount_minor': 400000})
    provider.request = AsyncMock(return_value=boundary)
    provider.snapshot = AsyncMock(return_value={**lot, 'server_time': '2026-11-17T00:00:01+00:00'})
    provider.history = AsyncMock(return_value=[])
    provider.submit = AsyncMock(return_value={'status': 'denied', 'code': 'auction_ended'})
    if boundary_code is None:
        with pytest.raises(AssertionError):
            asyncio.run(provider.exercise('equal_end', Dataset()))
        provider.submit.assert_not_awaited()
    else:
        assert asyncio.run(provider.exercise('equal_end', Dataset())).state == 'denied'
        provider.lot.assert_awaited_once_with('equal_end')
        provider.submit.assert_awaited_once()
        assert provider.snapshot.await_count == 3
        assert provider.request.await_args.kwargs == {'actor': 'seller', 'owner_read': True}


@pytest.mark.parametrize('changed,value', [
    (None, None), ('order_id', 'test-other-order'), ('watch_id', 'test-other-watch'),
    ('buyer_id', 'test-other-buyer'), ('current', False), ('state', 'expired_released')])
def test_allocation_requires_current_winning_commitment(changed, value):
    provider = NativeProvider(None, {}, None, None)
    provider.subjects[0] = 'test-buyer'
    receipt = {'won': True, 'order_id': 'test-order'}
    order = {'id': 'test-order', 'watch_id': 'test-watch', 'buyer_id': 'test-buyer',
             'listing_id': 'test-listing', 'state': 'awaiting_payment'}
    watch = {'watch_id': 'test-watch', 'listing_id': 'test-listing', 'status': 'reserved'}
    commitment = {'order_id': 'test-order', 'watch_id': 'test-watch',
                  'buyer_id': 'test-buyer', 'state': 'awaiting_payment', 'current': True}
    if changed:
        commitment[changed] = value
    provider.request = AsyncMock(side_effect=[receipt, receipt, {'order': order},
                                              {'items': [order]}, watch])
    provider.current_commitment = AsyncMock(return_value=commitment)
    journey = provider.load_allocation('test-auction', 0, lot={'listing_id': 'test-listing'})
    if changed:
        with pytest.raises(AssertionError):
            asyncio.run(journey)
    else:
        assert asyncio.run(journey)[-1] == commitment
    provider.current_commitment.assert_awaited_once_with('test-order')


@pytest.mark.parametrize('case', ['equal_end', 'after_end'])
@pytest.mark.parametrize('changed,value', [
    (None, None), ('mode', 'closed_winner'), ('accepted_sequence', 1),
    ('current_minor', 410000), ('ends_at', '2026-11-17T00:00:02+00:00')])
def test_deadline_denial_accepts_only_unchanged_empty_close(case, changed, value):
    lot = {'id': 'test-auction', 'ends_at': '2026-11-17T00:00:00+00:00',
           'revision': 1, 'accepted_sequence': 0, 'current_minor': 400000}
    closed = {**lot, 'mode': 'closed_no_sale', 'revision': 2}
    if changed:
        closed[changed] = value
    boundary = {'auction_id': lot['id'], 'ends_at': lot['ends_at'],
                'evaluated_at': lot['ends_at'], 'revision': 2,
                'accepted_sequence': 0, 'code': 'auction_committed'}
    provider = NativeProvider(None, {}, None, None)
    provider.lot = AsyncMock(return_value=lot)
    provider.command = AsyncMock(return_value={'amount_minor': 400000})
    provider.request = AsyncMock(side_effect=[boundary, closed, closed] if case == 'equal_end'
                                 else [closed, closed])
    provider.snapshot = AsyncMock(return_value={**lot, 'server_time': '2026-11-17T00:00:01+00:00'})
    provider.history = AsyncMock(return_value=[])
    provider.submit = AsyncMock(return_value={'status': 'denied', 'code': 'auction_committed'})
    if changed:
        with pytest.raises(AssertionError):
            asyncio.run(provider.exercise(case, Dataset()))
    else:
        assert asyncio.run(provider.exercise(case, Dataset())).state == 'denied'
        assert provider.history.await_count == 4
        assert [call.kwargs['replica'] for call in provider.request.await_args_list[-2:]] == [0, 1]
