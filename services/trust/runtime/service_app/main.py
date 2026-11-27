"""Trust composition preserves the canonical HTTP and transaction boundaries."""
from types import SimpleNamespace

from bt_runtime.app import db as foundation_db
from bt_runtime.app.main import create_app as foundation_create_app

from .discovery import bind, discover

migration_steps = bind(foundation_db.migration_steps, discover=discover)
migrate = bind(foundation_db.migrate, migration_steps=migration_steps)
ready = bind(foundation_db.ready, migration_steps=migration_steps)
_database = SimpleNamespace(create_pool=foundation_db.create_pool, ready=ready)
_create_app = bind(foundation_create_app, discover=discover, db=_database)


def create_app(settings=None):
    app = _create_app(settings)
    if app.state.settings.service_name != 'trust':
        raise ValueError('Trust runtime requires its authoritative service name')
    return app
