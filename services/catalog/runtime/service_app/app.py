"""Catalog composition uses the shared server and one module registry."""

from bt_runtime.app.main import create_app as shared_app
from service_app.discovery import configure


def create_app(settings=None):
    configure()
    return shared_app(settings)
