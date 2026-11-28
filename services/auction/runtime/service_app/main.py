from contextlib import asynccontextmanager
from .discovery import install_discovery
from bt_runtime.app.main import create_app as foundation_app
from .engine import AuctionEngine
from .proxy_v2 import calculate


def create_app(settings=None, dependencies=None):
    install_discovery()
    app = foundation_app(settings)
    # Preserve a discovered v2 provider; the old v1 hook remains historical.
    app.state.hooks.setdefault('auction.proxy.v2', calculate)
    engine = AuctionEngine(dependencies)
    app.state.auction = engine
    foundation_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with foundation_lifespan(app):
                yield
        finally:
            await engine.dependencies.close()

    app.router.lifespan_context = lifespan
    return app
