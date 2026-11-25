import asyncio
from types import SimpleNamespace
from test_factor import load

adapter = load('factor_adapter', 'services/identity/modules/two-factor/adapter.py')


def request(provider=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(two_factor_current_provider=provider)))


def test_missing_provider_is_unavailable_and_private():
    result = asyncio.run(adapter.invoke(request()))
    assert result.status_code == 503
    assert result.headers['cache-control'] == 'no-store'
    assert b'unavailable' in result.body


def test_timeout_is_pending_not_success():
    class Provider:
        async def command(self, *_):
            raise TimeoutError()
    result = asyncio.run(adapter.invoke(request(Provider()), object()))
    assert result.status_code == 503
    assert result.headers['cache-control'] == 'no-store'


def test_browser_cannot_supply_actor_session_or_recovery():
    import pytest
    for field in ('actor_id', 'session_id', 'controllers'):
        with pytest.raises(ValueError):
            adapter.BrowserCommand(schema_version=1, operation_id='operation-private-1',
                                   kind='enroll', expected_revision=0, **{field: 'other'})
    with pytest.raises(ValueError):
        adapter.BrowserCommand(schema_version=1, operation_id='operation-private-1',
                               kind='revoke_ack', expected_revision=0)


def test_validation_responses_never_echo_private_input():
    from fastapi import FastAPI
    import httpx

    async def check():
        app = FastAPI()
        app.include_router(adapter.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for extra in ({'current_password': 'private-value-' * 20}, {'proof': 'private-code-' * 20},
                          {'unexpected': 'private-extra'}, {'expected_revision': 'private-revision'}):
                body = {'schema_version': 1, 'operation_id': 'operation-private-1',
                        'kind': 'enroll', 'expected_revision': 0, **extra}
                result = await client.post('/v1/two-factor', json=body)
                assert result.status_code == 422
                assert result.json() == {'error': {'code': 'invalid_proof'}}
                assert result.headers['cache-control'] == 'no-store'
                assert result.headers['pragma'] == 'no-cache'
            result = await client.post('/v1/two-factor', content='{broken')
            assert result.status_code == 422
            assert result.headers['cache-control'] == 'no-store'
            assert result.json() == {'error': {'code': 'invalid_proof'}}
            result = await client.post('/v1/two-factor', content=b'\xff',
                                       headers={'Content-Type': 'application/json'})
            assert result.status_code == 400
            assert result.headers['cache-control'] == 'no-store'
            assert result.headers['pragma'] == 'no-cache'
            assert result.json() == {'error': {'code': 'invalid_proof'}}
    asyncio.run(check())
