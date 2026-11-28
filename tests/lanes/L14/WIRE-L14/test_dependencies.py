import asyncio
import importlib
from types import SimpleNamespace
import httpx
import pytest
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError


@pytest.mark.asyncio
async def test_each_dependency_times_out_opens_circuit_and_isolates_saturation(runtime):
    service, _ = runtime
    names = ('identity', 'catalog', 'pricing', 'orders') if service == 'auction' else (
        'identity', 'communications', 'catalog', 'orders', 'service-operations', 'auction')
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})
    async def healthy(request):
        return httpx.Response(200, json={'state': 'pending'})
    other = DependencyClient('other', 'http://other', transport=httpx.MockTransport(healthy))
    try:
        for name in names:
            client = DependencyClient(name, 'http://' + name, timeout=.01, concurrency=1,
                                      failure_threshold=1, transport=httpx.MockTransport(slow))
            try:
                first = asyncio.create_task(client.request('GET', '/v1/example'))
                await asyncio.sleep(0)
                assert (await client.request('GET', '/v1/example')).reason == 'saturated'
                assert (await other.request('GET', '/v1/example')).json()['state'] == 'pending'
                assert (await first).reason == 'timeout'
                assert (await client.request('GET', '/v1/example')).reason == 'circuit_open'
            finally:
                await client.aclose()
    finally:
        await other.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(403, 'denied'), (409, 'stale'), (503, 'unavailable')])
async def test_adapters_never_turn_denied_stale_or_lost_response_into_success(runtime, status, code):
    service, _ = runtime
    class Client:
        async def request(self, *args, **kwargs):
            if status == 503:
                return Unavailable('identity', 'timeout')
            return httpx.Response(status, json={'state': code})
    request = SimpleNamespace(headers={}, state=SimpleNamespace(request_id='l14-example'),
                              app=SimpleNamespace(state=SimpleNamespace(identity=Client())))
    error = AccessDenied if status == 403 else PublicError
    if service == 'auction':
        dependencies = importlib.import_module('service_app.dependencies').Dependencies({'identity': Client()})
        with pytest.raises(error):
            await dependencies.json('identity', 'GET', '/v1/example', request)
    else:
        peers = importlib.import_module('service_app.peers')
        with pytest.raises(error):
            await peers.call(request, 'identity', 'GET', '/v1/example')
