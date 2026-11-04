"""Real Identity, Eligibility and Trust runtimes; disposable DBs, no authority fixtures."""
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import os
from pathlib import Path
import signal
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import uvicorn
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from browser_harness import ManagedServer
from proof_database import database


def provider_factory(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_app


async def main():
    if os.getenv('BT_L09_CONNECTED_PROOF')!='1':
        raise RuntimeError('Explicit connected-proof mode is required')
    root=Path('/workspace')
    origin=os.environ['BT_L09_PROOF_ORIGIN']
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    os.environ.update({'BT_AUTH_PRIVATE_KEY':private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),
        'BT_WEB_ORIGIN':origin,'BT_ALLOWED_WEB_ORIGINS':origin,'BT_LOCAL_HTTP':'1',
        'BT_IDENTITY_URL':'http://127.0.0.1:18301','BT_IDENTITY_API_URL':'http://127.0.0.1:18301',
        'BT_CATALOG_URL':'http://127.0.0.1:18302','BT_CATALOG_API_URL':'http://127.0.0.1:18302',
        'BT_COMMUNICATIONS_URL':'http://127.0.0.1:18308'})
    # The owning Identity helper is loaded from its real runtime, not a replica.
    sys.path.insert(0,str(root/'services/identity/runtime'))
    factories={service:provider_factory(root/f'services/{service}/runtime/service_app/main.py','l09_'+service+'_provider') for service in ('identity','eligibility')}
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for value in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(value,stop.set)
    async with AsyncExitStack() as stack:
        apps=[]
        for service,port in (('identity',18301),('eligibility',18306),('trust',18307)):
            modules=root/'services'/service/'modules'
            db=await stack.enter_async_context(database(os.environ['TEST_DATABASE_ADMIN_URL'],modules))
            settings=Settings(service_name=service,database_url=db.runtime_url,modules_path=modules,auth_public_key=public,service_auth_public_key=public)
            apps.append((factories.get(service,create_app)(settings),port))
        servers=[ManagedServer(uvicorn.Config(app,host='0.0.0.0',port=port,access_log=False,log_level='warning')) for app,port in apps]
        tasks=[asyncio.create_task(server.serve()) for server in servers]
        try:
            for _ in range(200):
                if all(server.started for server in servers):
                    break
                if any(task.done() for task in tasks):
                    raise RuntimeError('A connected provider failed to start')
                await asyncio.sleep(.1)
            else:
                raise RuntimeError('Connected provider startup deadline exceeded')
            print('L09 REAL IDENTITY PROOF READY — register through the actual UI; no grants, custody or outcomes seeded',flush=True)
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
    print('Connected proof databases and roles removed; shared provider processes untouched',flush=True)


if __name__=='__main__':
    asyncio.run(main())
