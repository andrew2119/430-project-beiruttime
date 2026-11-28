"""One local proof runtime on a restricted disposable DB; no ordinary domain DB is touched."""

import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uvicorn
from bt_runtime.testing import database_access
from bt_runtime.app.settings import Settings


async def main():
    state = Path(os.environ["L13_STATE_DIR"])
    state.mkdir(parents=True, exist_ok=True)
    service = os.environ["BT_SERVICE_NAME"]
    generator = database_access.__wrapped__(SimpleNamespace(param="service"), state)
    access = await generator.__anext__()
    try:
        os.environ["BT_DATABASE_URL"] = access.runtime_url
        private = state / (service + ".json")
        private.write_text(json.dumps({"runtime_url": access.runtime_url}))
        private.chmod(0o600)
        module = importlib.import_module(
            "service_app.main"
            if importlib.util.find_spec("service_app.main")
            else "bt_runtime.app.main"
        )
        app = module.create_app(
            Settings(database_url=access.runtime_url, service_name=service)
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=os.environ.get("L13_BIND", "127.0.0.1"),
                port=int(os.environ["L13_PORT"]),
                log_level="warning",
                access_log=False,
            )
        )
        await server.serve()
    finally:
        await generator.aclose()


asyncio.run(main())
