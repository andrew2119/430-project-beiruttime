"""Orders process composition for the complete lane range."""

import re

from bt_runtime import modules

# Apply before application construction and before migration planning. Both shared
# consumers resolve these validators from the same discovery module.
modules.MODULE_ID = re.compile(r'^L(?:0[0-9]|1[0-9]|2[0-5])\.[a-z][a-z0-9.-]+$')
modules.MIGRATION = re.compile(r'^L(?:0[0-9]|1[0-9]|2[0-5])_[0-9]{4}_[a-z0-9_]+\.sql$')


def create_app(settings=None):
    from bt_runtime.app.main import create_app as runtime_app
    from bt_runtime.app.settings import Settings

    settings = settings or Settings(service_name="orders")
    if settings.service_name != "orders":
        raise ValueError("Orders requires its own service identity")
    return runtime_app(settings)
