import asyncio
from bt_runtime.app.db import migrate
from bt_runtime.app.settings import Settings
from .discovery import install_discovery

if __name__ == '__main__':
    install_discovery()
    settings = Settings()
    asyncio.run(migrate(settings.database_url, settings.modules_path))
