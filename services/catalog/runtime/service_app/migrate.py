import asyncio
from bt_runtime.app.db import migrate
from bt_runtime.app.settings import Settings
from service_app.discovery import configure

if __name__ == "__main__":
    configure()
    settings = Settings()
    asyncio.run(migrate(settings.database_url, settings.modules_path))
