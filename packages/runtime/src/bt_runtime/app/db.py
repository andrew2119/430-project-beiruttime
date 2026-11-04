"""CP 4A/4B/4C: async SQL, checksummed ledger and connection-bound UoW."""
import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
import asyncpg
from bt_runtime.modules import discover

MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'


def migration_steps(modules_path: Path | None = None):
    core = [(p.name, hashlib.sha256(p.read_bytes()).hexdigest(), p.read_text())
            for p in sorted(MIGRATIONS.glob('*.sql'))]
    modules = discover(modules_path if modules_path is not None else Path(os.environ.get('BT_MODULES_PATH', '/app/modules')))
    return core + [(module.id + '/' + p.name, hashlib.sha256(p.read_bytes()).hexdigest(), p.read_text())
                   for module in modules for p in module.migrations]


async def migrate(url: str, modules_path: Path | None = None) -> None:
    conn = await asyncpg.connect(url, command_timeout=30)
    try:
        async with conn.transaction():
            await conn.execute("SET LOCAL lock_timeout='10s'")
            await conn.execute("SELECT pg_advisory_xact_lock(1920261104)")
            await conn.execute('''CREATE TABLE IF NOT EXISTS migration_ledger (
                step_id text PRIMARY KEY, checksum text NOT NULL CHECK(length(checksum)=64),
                applied_at timestamptz NOT NULL DEFAULT now())''')
            applied = {r['step_id']: r['checksum'] for r in await conn.fetch('SELECT * FROM migration_ledger')}
            steps = migration_steps(modules_path)
            if set(applied) - {s[0] for s in steps}:
                raise RuntimeError('Unknown migration in ledger')
            for name, checksum, sql in steps:
                if name in applied:
                    if applied[name] != checksum:
                        raise RuntimeError(f'Migration checksum changed: {name}')
                    continue
                await conn.execute(sql)
                await conn.execute('INSERT INTO migration_ledger(step_id,checksum) VALUES($1,$2)', name, checksum)
            # Default table grants permit domain DML, but the ledger is owner-write-only.
            owner = await conn.fetchval('SELECT current_user')
            if owner.endswith('_owner'):
                runtime = owner.removesuffix('_owner').replace('"', '""')
                await conn.execute(f'REVOKE INSERT, UPDATE, DELETE ON migration_ledger FROM "{runtime}"')
    finally:
        await conn.close()


async def create_pool(url: str, size: int = 5):
    return await asyncpg.create_pool(url, min_size=1, max_size=size, command_timeout=3,
        server_settings={'statement_timeout': '3000', 'lock_timeout': '1000',
                         'idle_in_transaction_session_timeout': '5000'})


async def ready(pool, modules_path: Path | None = None) -> bool:
    async with pool.acquire(timeout=1) as conn:
        rows = await conn.fetch('SELECT step_id,checksum FROM migration_ledger')
        expected = {name: checksum for name, checksum, _ in migration_steps(modules_path)}
        return {r['step_id']: r['checksum'] for r in rows} == expected


@asynccontextmanager
async def unit_of_work(pool, *, lock_key: str | None = None):
    async with pool.acquire(timeout=2) as conn:
        async with conn.transaction(isolation='read_committed'):
            if lock_key is not None:
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', lock_key)
            yield conn
