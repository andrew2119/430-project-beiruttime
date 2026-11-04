"""One Eligibility runtime; dependency bulkheads live for exactly its lifespan."""
import os
from contextlib import asynccontextmanager
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app as foundation_app
from bt_runtime.app.settings import Settings


def create_app(settings=None):
    settings = settings or Settings()
    settings.auth_public_key = settings.auth_public_key.replace('\\n','\n')
    settings.service_auth_public_key = settings.service_auth_public_key.replace('\\n','\n')
    app = foundation_app(settings)
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        app.state.identity = DependencyClient('identity', os.environ.get('BT_IDENTITY_API_URL','http://identity:8000'), timeout=1.2, concurrency=4)
        app.state.catalog = DependencyClient('catalog', os.environ.get('BT_CATALOG_API_URL','http://catalog:8000'), timeout=1.2, concurrency=4)
        try:
            async with original(app):
                yield
        finally:
            await app.state.identity.aclose()
            await app.state.catalog.aclose()
    app.router.lifespan_context = lifespan
    return app
