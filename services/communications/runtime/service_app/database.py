"""Use the shared transaction ledger with Communications discovery."""
from types import FunctionType
from bt_runtime.app import db
from .discovery import runtime_discover as discover


def bind(function, **overrides):
    return FunctionType(function.__code__, {**function.__globals__, **overrides},
        function.__name__, function.__defaults__, function.__closure__)


migration_steps = bind(db.migration_steps, discover=discover)
migrate = bind(db.migrate, migration_steps=migration_steps)
ready = bind(db.ready, migration_steps=migration_steps)
create_pool = db.create_pool
unit_of_work = db.unit_of_work
