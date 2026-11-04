from contextlib import asynccontextmanager
from bt_runtime.app.main import create_app as foundation_app
from .engine import AuctionEngine


def create_app(settings=None, dependencies=None):
    app = foundation_app(settings)
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
