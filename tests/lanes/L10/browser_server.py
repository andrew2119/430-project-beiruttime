"""Disposable proof server. Only dependency transports are fixtures; Catalog uses PostgreSQL.

Never use this entry point for the connected marketplace acceptance or production.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
import uvicorn
from bt_bulkheads import DependencyClient
from bt_runtime.app.db import migrate
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.testing import database_access
from test_options import directory, identity, populate


async def main():
    access_context = asynccontextmanager(database_access.__wrapped__)
    async with access_context() as access:
        modules = Path("/app/modules")
        await migrate(access.owner_url, modules)
        app = create_app(Settings(service_name="catalog", database_url=access.runtime_url, modules_path=modules))
        module = next(m for m in app.state.modules if m.id == "L10.options-color")
        clients = module.load("dependencies.py:clients")(app)
        for name in ("identity", "directory"):
            await clients[name].aclose()
        clients["identity"] = DependencyClient("identity", "http://identity", transport=httpx.MockTransport(identity))
        clients["directory"] = DependencyClient(
            "directory", "http://directory", transport=httpx.MockTransport(directory)
        )
        lifecycle = app.router.lifespan_context

        @asynccontextmanager
        async def seeded_lifespan(app):
            async with lifecycle(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://catalog"
                ) as client:
                    await populate(client)
                yield

        app.router.lifespan_context = seeded_lifespan
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000, access_log=False))
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
