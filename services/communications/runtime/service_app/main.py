"""One Communications runtime; each module contributes only its scoped routes."""
import os
from contextlib import asynccontextmanager
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app as foundation_app


def create_app(settings=None):
    app = foundation_app(settings)
    original = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        clients = {name: DependencyClient(name, os.environ.get(name.upper() + '_API_URL', 'http://' + name + ':8000'), timeout=1.2, concurrency=4)
                   for name in ('identity', 'pricing', 'orders', 'auction', 'trust')}
        for name, client in clients.items():
            setattr(app.state, name, client)
        try:
            async with original(app):
                yield
        finally:
            for client in clients.values():
                await client.aclose()
    app.router.lifespan_context = lifespan
    return app
