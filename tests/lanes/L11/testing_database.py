"""Disposable core-only SQL for standalone proofs using the current foundation fixture."""
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from bt_runtime.testing import database_access

ROOT = next((path for path in Path(__file__).resolve().parents if (path / 'compose.yaml').is_file()), Path('/'))


@asynccontextmanager
async def disposable_database():
    if not (ROOT / '.venv').is_dir():
        raise RuntimeError('Standalone proofs require the repository-local .venv scratch directory')
    with TemporaryDirectory(prefix='l11-database-', dir=ROOT / '.venv') as temporary:
        fixture = database_access.__wrapped__(SimpleNamespace(param='core-only'), Path(temporary))
        access = await anext(fixture)
        try:
            yield access
        finally:
            await fixture.aclose()
