"""Run actual L09 modules against explicit dependency fixtures in disposable DBs."""
import asyncio
from contextlib import AsyncExitStack, contextmanager
import os
from pathlib import Path
import signal
import httpx
import uvicorn
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from dependency_fixtures import fixture_app, PASSWORD, ORG, OTHER_ORG
from proof_database import database


class ManagedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield


async def main():
    if os.getenv('BT_L09_CONTRACT_PROOF')!='1':
        raise RuntimeError('Explicit contract-proof mode is required')
    root=Path('/workspace')
    origin=os.environ['BT_L09_PROOF_ORIGIN']
    directory=(root/'services/service-operations/modules/directory/module.json').exists()
    os.environ.update({'BT_IDENTITY_URL':'http://127.0.0.1:18301','BT_CATALOG_URL':'http://127.0.0.1:18301',
        'IDENTITY_API_URL':'http://127.0.0.1:18301',
        'BT_SERVICE_OPERATIONS_URL':'http://127.0.0.1:18309' if directory else 'http://127.0.0.1:18301','BT_ORDERS_URL':'http://127.0.0.1:18301',
        'BT_TRUST_URL':'http://127.0.0.1:18307','BT_COMMUNICATIONS_URL':'http://127.0.0.1:18308'})
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for value in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(value,stop.set)
    async with AsyncExitStack() as stack:
        apps=[(fixture_app(origin),18301)]
        for service,port in (('trust',18307),('communications',18308),('service-operations',18309)):
            modules=root/'services'/service/'modules'
            db=await stack.enter_async_context(database(os.environ['TEST_DATABASE_ADMIN_URL'],modules))
            apps.append((create_app(Settings(service_name=service,database_url=db.runtime_url,modules_path=modules)),port))
        servers=[ManagedServer(uvicorn.Config(app,host='0.0.0.0',port=port,access_log=False,log_level='warning')) for app,port in apps]
        tasks=[asyncio.create_task(server.serve()) for server in servers]
        try:
            for _ in range(200):
                if all(server.started for server in servers):
                    break
                if any(task.done() for task in tasks):
                    raise RuntimeError('A contract-proof service failed to start')
                await asyncio.sleep(.1)
            else:
                raise RuntimeError('Contract-proof startup deadline exceeded')
            if directory:
                # Labeled sample profiles are published through the actual provider
                # command, never SQL seeding or an invented provider success response.
                async with httpx.AsyncClient(timeout=5) as client:
                    for email,organization in (('technical@example.invalid',ORG),('other-business@example.invalid',OTHER_ORG)):
                        login=await client.post('http://127.0.0.1:18301/v1/accounts/login',headers={'Origin':origin},json={'email':email,'password':PASSWORD})
                        login.raise_for_status()
                        published=await client.put('http://127.0.0.1:18309/v1/directory/businesses/'+organization,
                            headers={'Authorization':'Bearer '+login.json()['access_token'],'Idempotency-Key':'l09-directory-sample-v1'},json={
                                'expected_revision':0,'capabilities':['maintenance'],'contact':'sample@example.invalid',
                                'visit_en':'SAMPLE visits by arrangement','visit_ar':'زيارات تجريبية بترتيب مسبق',
                                'scope_en':'SAMPLE assessment only; no custody or completed work','scope_ar':'تقييم تجريبي فقط دون استلام أو عمل منجز','published':True})
                        published.raise_for_status()
                print('Actual Directory V1 sample publication complete; Identity authority remains fixture-only',flush=True)
            print('L09 CONTRACT PROOF READY — explicit dependency fixtures; no custody or completed-work result',flush=True)
            await stop.wait()
        finally:
            for server in servers:
                server.should_exit=True
            try:
                await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),timeout=15)
            except TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
    print('L09 contract-proof databases and roles removed; shared storage preserved',flush=True)


if __name__=='__main__':
    asyncio.run(main())
