import asyncio
from bt_runtime.app import db
from bt_runtime.app.settings import Settings
from .modules import discover


def run():
    db.discover = discover
    settings = Settings()
    asyncio.run(db.migrate(settings.database_url, settings.modules_path))


if __name__ == '__main__':
    run()
