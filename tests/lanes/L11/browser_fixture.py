"""Disposable browser proof only: real module SQL/HTTP with a labeled Identity contract fixture.

Run from repository root with TEST_DATABASE_ADMIN_URL set to local maintenance DB.
The fixture never starts or changes an ordinary Catalog or Identity runtime.
"""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import signal
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from bt_runtime.testing import database_access
from .conftest import module_stack, BRAND
from .service_operations_helpers import headers
from .service_operations_tests_data import profile, option


@asynccontextmanager
async def disposable():
    fixture = database_access.__wrapped__()
    access = await anext(fixture)
    try:
        yield access
    finally:
        await fixture.aclose()


class ProofServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # One signal owner shuts down all three proof servers and their disposable databases.
        yield


async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with disposable() as directory_db, disposable() as catalog_db:
        async with module_stack('directory',directory_db.runtime_url,directory_db.owner_url) as directory, module_stack('movement',catalog_db.runtime_url,catalog_db.owner_url) as movement:
            dc, directory_app, identity = directory
            mc, movement_app, movement_identity = movement
            # Loopback-only fault controls belong to this disposable proof, never a domain module.
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
            identity_app = FastAPI()
            @identity_app.api_route('/{path:path}',methods=['GET','POST'])
            async def identity_route(path:str,request:Request):
                response=identity.handle(httpx.Request(request.method,str(request.url),headers=dict(request.headers)))
                return JSONResponse(response.json() if response.content else {},status_code=response.status_code)
            servers=[ProofServer(uvicorn.Config(app,host='127.0.0.1',port=port,lifespan='off',log_level='warning')) for app,port in ((directory_app,38109),(movement_app,38102),(identity_app,38101))]
            tasks=[asyncio.create_task(server.serve()) for server in servers]
            try:
                await stop.wait()
            finally:
                for server in servers:
                    server.should_exit=True
                await asyncio.gather(*tasks)


if __name__=='__main__':
    asyncio.run(main())
