import asyncio
import threading
import pytest
from bt_contracts_core.errors import PublicError
from test_accounts import register,environment as environment,keys as keys


@pytest.mark.asyncio
async def test_legacy_hash_profile_is_read_only_and_upgraded_on_login(environment):
    app,client=environment
    await register(client)
    legacy='scrypt$AAAAAAAAAAAAAAAAAAAAAA==$+RF4mCDRd3vqijnTN1XYGJ7Ugd+50DsEb4BfXrVOdQ0='
    async with app.state.pool.acquire() as tx:
        await tx.execute('UPDATE identity_accounts SET password_hash=$1',legacy)
    response=await client.post('/v1/accounts/login',json={'email':'sample@example.test','password':'not-a-valid-password'})
    assert response.status_code==200
    async with app.state.pool.acquire() as tx:
        assert (await tx.fetchval('SELECT password_hash FROM identity_accounts')).startswith('scrypt$16384$8$5$')


@pytest.mark.asyncio
async def test_cancelled_password_work_retains_capacity_until_thread_finishes(environment):
    app,_=environment
    module=next(module for module in app.state.modules if module.id=='L01.accounts')
    work=module.load('security.py:password_work')
    slots=module.load('security.py:hash_slots')
    started,finish=threading.Event(),threading.Event()
    def blocking_hash():
        started.set();finish.wait(2);return 'synthetic-hash-result'
    task=asyncio.create_task(work(blocking_hash))
    try:
        assert await asyncio.to_thread(started.wait,1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert slots._value==1
        await slots.acquire()
        try:
            with pytest.raises(PublicError):
                await work(lambda:'must-not-run')
        finally:
            slots.release()
    finally:
        finish.set()
    async def released():
        while slots._value!=2:
            await asyncio.sleep(.01)
    await asyncio.wait_for(released(),2)
