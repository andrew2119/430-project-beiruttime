"""Disposable SQL/HTTP proof: V1 business authority fixture, optionally real Accounts routes.

No ordinary domain database or shared runtime is changed. Real-Accounts mode proves
buyer sessions and owner-private UI persistence; it does not certify business onboarding.
"""
import asyncio
from contextlib import AsyncExitStack, contextmanager
import os
import signal
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .conftest import IdentityFixture, module_stack, BRAND
from .service_operations_helpers import headers
from .service_operations_tests_data import profile, option
from .real_accounts import accounts_routes
from .testing_database import disposable_database


class ProofServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # One signal owner shuts down every proof server and its disposable database.
        yield


async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with AsyncExitStack() as stack:
        directory_db = await stack.enter_async_context(disposable_database())
        catalog_db = await stack.enter_async_context(disposable_database())
        accounts_app = None
        if os.environ.get('L11_REAL_ACCOUNTS_PROOF') == '1':
            accounts_db = await stack.enter_async_context(disposable_database())
            accounts_app = await stack.enter_async_context(accounts_routes(accounts_db))
        dc, directory_app, identity = await stack.enter_async_context(module_stack(
            'directory',directory_db.runtime_url,directory_db.owner_url,accounts_app))
        mc, movement_app, movement_identity = await stack.enter_async_context(module_stack(
            'movement',catalog_db.runtime_url,catalog_db.owner_url,accounts_app))
        # Loopback-only fault controls never belong to a production module.
        @directory_app.post('/proof/dependency')
        async def directory_dependency(unavailable: bool):
            identity.unavailable = unavailable
            return {'unavailable': unavailable}

        @movement_app.post('/proof/dependency')
        async def movement_dependency(unavailable: bool):
            movement_identity.unavailable = unavailable
            return {'unavailable': unavailable}

        published=await dc.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())
        published.raise_for_status()
        published=await mc.put('/v1/options/movement/00000000-0011-4000-8000-000000000003',json=option(),headers=headers())
        published.raise_for_status()
        web_authority = IdentityFixture()
        identity_app = accounts_app or FastAPI()
        if accounts_app:
            @identity_app.middleware('http')
            async def fixture_business_authority(request: Request, call_next):
                opaque_fixture_tokens = {'Bearer buyer','Bearer other','Bearer brand','Bearer dealer','Bearer cross'}
                fixture_request = request.url.path.startswith('/v1/businesses/') or (
                    request.url.path == '/internal/v1/principal' and request.headers.get('Authorization') in opaque_fixture_tokens)
                if fixture_request:
                    response=web_authority.handle(httpx.Request(request.method,str(request.url),headers=dict(request.headers)))
                    return JSONResponse(response.json() if response.content else {},status_code=response.status_code)
                return await call_next(request)
        else:
            @identity_app.api_route('/{path:path}',methods=['GET','POST'])
            async def identity_route(path:str,request:Request):
                response=web_authority.handle(httpx.Request(request.method,str(request.url),headers=dict(request.headers)))
                return JSONResponse(response.json() if response.content else {},status_code=response.status_code)
        servers=[ProofServer(uvicorn.Config(app,host='127.0.0.1',port=port,lifespan='off',log_level='warning'))
            for app,port in ((directory_app,38109),(movement_app,38102),(identity_app,38101))]
        tasks=[asyncio.create_task(server.serve()) for server in servers]
        try:
            await stop.wait()
        finally:
            for server in servers:
                server.should_exit=True
            await asyncio.gather(*tasks)


if __name__=='__main__':
    asyncio.run(main())
