from bt_runtime.app.main import create_app as foundation_app
from bt_runtime.app.settings import Settings


def create_app(settings=None):
    settings = settings or Settings()
    settings.auth_public_key = settings.auth_public_key.replace('\\n','\n')
    settings.service_auth_public_key = settings.service_auth_public_key.replace('\\n','\n')
    return foundation_app(settings)
