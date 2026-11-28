from contextlib import asynccontextmanager
from .discovery import install_discovery
from bt_runtime.app.main import create_app as foundation_app
from .engine import AuctionEngine
from .proxy_v2 import calculate
from .private_maximum import PrivateMaximum
from .buyer_activity import router as activity_router
from .buyer_support import router as support_router


def create_app(settings=None, dependencies=None):
    install_discovery()
    app = foundation_app(settings)
    # Preserve a discovered v2 provider; the old v1 hook remains historical.
    app.state.hooks.setdefault('auction.proxy.v2', calculate)
    engine = AuctionEngine(dependencies)
    app.state.auction = engine
    app.state.proxy_private_v2 = PrivateMaximum(engine)
    app.include_router(activity_router)
    app.include_router(support_router)
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
