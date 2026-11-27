"""Service-local composition of the shared runtime."""
from bt_runtime.app import db, main
from .modules import discover


def create_app(settings=None):
    # Startup and readiness must calculate the same complete migration plan.
    main.discover = discover
    db.discover = discover
    return main.create_app(settings)
