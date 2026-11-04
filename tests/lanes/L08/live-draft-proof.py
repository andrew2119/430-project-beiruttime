"""Ephemeral, real PostgreSQL draft API for authenticated browser verification only."""

import asyncio
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import uvicorn
from bt_runtime.testing import database_access
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings


async def main():
    # The shared test adapter creates restricted roles and never migrates an ordinary domain DB.
    temporary = TemporaryDirectory(prefix="l08-live-draft-")
    generator = inspect.unwrap(database_access)(SimpleNamespace(param="service"), Path(temporary.name))
    try:
        access = await anext(generator)
        app = create_app(Settings(service_name="catalog", database_url=access.runtime_url))
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000, access_log=False, log_level="warning"))
        await server.serve()
    finally:
        await generator.aclose()
        temporary.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
