import asyncio
from .db import migrate
from .settings import Settings

if __name__ == '__main__':
    asyncio.run(migrate(Settings().database_url))
