import asyncio
from bt_runtime import demo_seed_deadline
from bt_runtime.app.db import migrate
from bt_runtime.app.settings import Settings

if __name__ == "__main__":
    settings = Settings()
    asyncio.run(migrate(settings.database_url, settings.modules_path))
    # Off unless BT_DEMO_SEED is set. Only after the migrations have committed, the optional demo seed runs in a
    # separately supervised child process: this step waits for it at most demo_seed_deadline.BOUND_SECONDS, never
    # sees its failures and never fails because of it. Unset, it returns at once and starts nothing.
    demo_seed_deadline.supervise()
