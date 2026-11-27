"""One Communications runtime; each module contributes only its scoped routes."""
import os
import re
from contextlib import asynccontextmanager
from bt_bulkheads import DependencyClient
from types import FunctionType
from bt_runtime.app.main import create_app as foundation_app
from . import database
from .discovery import runtime_discover as discover


def create_app(settings=None):
    # Bind service-local discovery and migration checks without changing shared state.
    composition = FunctionType(foundation_app.__code__,
        {**foundation_app.__globals__, 'discover': discover, 'db': database},
        foundation_app.__name__, foundation_app.__defaults__, foundation_app.__closure__)
    app = composition(settings)
    registered = set()
    for route in app.routes:
        path = re.sub(r'\{[^}]+\}', '{}', route.path)
        for method in getattr(route, 'methods', ()):
            key = (method, path)
            if key in registered:
                raise ValueError('Duplicate Communications route')
            registered.add(key)
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
