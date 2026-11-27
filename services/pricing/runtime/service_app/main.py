"""Domain runtime with process-owned, separately bounded upstream pools."""
import os
from contextlib import asynccontextmanager
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app as foundation_app


def create_app(settings=None):
    app = foundation_app(settings)
    original = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        clients = {name: DependencyClient(name, os.environ.get(name.upper().replace('-', '_') + '_API_URL', 'http://' + name + ':8000'), timeout=1.2, concurrency=4)
                   for name in ('identity', 'communications', 'catalog', 'orders', 'service-operations', 'auction')}
        for name, client in clients.items():
            setattr(app.state, name.replace('-', '_'), client)
        try:
            async with original(app):
                yield
        finally:
            for client in clients.values():
                await client.aclose()
    app.router.lifespan_context = lifespan
    return app
