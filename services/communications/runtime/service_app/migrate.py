import asyncio
from .database import migrate
from bt_runtime.app.settings import Settings

if __name__ == '__main__':
    settings = Settings()
    asyncio.run(migrate(settings.database_url, settings.modules_path))
