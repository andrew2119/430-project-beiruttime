import json
import httpx
import pytest
from test_accounts import environment as environment,keys as keys


@pytest.mark.asyncio
async def test_opt_in_demo_uses_real_account_and_private_case_operations(environment,monkeypatch):
    app,_=environment
    module=next(module for module in app.state.modules if module.id=='L01.accounts')
    seed=module.load('fixtures.py:seed')
    client_type=httpx.AsyncClient
    monkeypatch.setenv('BT_DEMO_BUYER_PASSWORD','Synthetic-fixture-password!')
    monkeypatch.setenv('BT_DEMO_BUYER_EMAIL','fixture-buyer@example.test')
    monkeypatch.setattr(httpx,'AsyncClient',lambda **options:client_type(transport=httpx.ASGITransport(app=app),**options))
    first=await seed(app.state.settings)
    second=await seed(app.state.settings)
    assert first==second and first['sample'] and first['application_status']=='pending'
    assert first['session_cleanup_confirmed'] is True
    assert not any(value in json.dumps(first) for value in ['password','access_token','DEMO:'])
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM identity_accounts')==1
        assert await tx.fetchval('SELECT count(*) FROM identity_private_applications')==1
        assert await tx.fetchval('SELECT count(*) FROM identity_access_grants')==0
        assert await tx.fetchval('SELECT count(*) FROM identity_sessions WHERE revoked_at IS NULL')==0


@pytest.mark.asyncio
async def test_demo_refuses_missing_secret_or_real_recipient_without_writes(environment,monkeypatch):
    app,_=environment
    module=next(module for module in app.state.modules if module.id=='L01.accounts')
    seed=module.load('fixtures.py:seed')
    monkeypatch.delenv('BT_DEMO_BUYER_PASSWORD',raising=False)
    with pytest.raises(RuntimeError):
        await seed(app.state.settings)
    monkeypatch.setenv('BT_DEMO_BUYER_PASSWORD','Synthetic-fixture-password!')
    monkeypatch.setenv('BT_DEMO_BUYER_EMAIL','not-a-synthetic-recipient@example.com')
    with pytest.raises(RuntimeError):
        await seed(app.state.settings)
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM identity_accounts')==0
