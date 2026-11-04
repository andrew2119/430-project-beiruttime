"""Disposable core-only SQL for standalone proofs using the current foundation fixture."""
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from bt_runtime.testing import database_access

ROOT = Path(__file__).resolve().parents[3]


@asynccontextmanager
async def disposable_database():
    with TemporaryDirectory(prefix='l11-database-', dir=ROOT / '.venv') as temporary:
        fixture = database_access.__wrapped__(SimpleNamespace(param='core-only'), Path(temporary))
        access = await anext(fixture)
        try:
            yield access
        finally:
            await fixture.aclose()
