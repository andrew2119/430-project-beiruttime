"""Exercise the shared runner with a local transactional connection substitute."""
import copy
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from bt_runtime.app import db

from fixtures import DOMAINS

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("domain", DOMAINS)
def test_committed_module_lookup_and_checksum(domain):
    assert Path(db.__file__).resolve().is_relative_to(ROOT / "packages" / "runtime" / "src")
    root = ROOT / "services" / domain / "modules"
    assert root.is_dir()
    steps = db.migration_steps(root)
    assert len({name for name, _, _ in steps}) == len(steps)
    files = list(db.MIGRATIONS.glob("*.sql")) + list(root.rglob("*.sql"))
    hashes = {hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    assert all(checksum in hashes for _, checksum, _ in steps)
    assert any("/" in name for name, _, _ in steps)


class Connection:
    def __init__(self):
        self.ledger = {}
        self.statements = []
        self.closed = False

    @asynccontextmanager
    async def transaction(self):
        before = copy.deepcopy((self.ledger, self.statements))
        try:
            yield
        except Exception:
            self.ledger, self.statements = before
            raise

    async def execute(self, sql, *values):
        if sql == "synthetic invalid statement":
            raise ValueError("Synthetic migration failure")
        self.statements.append(sql)
        if sql.startswith("INSERT INTO migration_ledger"):
            self.ledger[values[0]] = values[1]

    async def fetch(self, _):
        return [{"step_id": key, "checksum": value} for key, value in self.ledger.items()]

    async def fetchval(self, _):
        return "synthetic_runtime"

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_actual_runner_atomic_failure_retry_duplicate_checksum_unknown(monkeypatch):
    connection = Connection()

    async def connect(*_, **__):
        return connection

    steps = [("L24.synthetic/1", "a" * 64, "synthetic create"),
             ("L24.synthetic/2", "b" * 64, "synthetic invalid statement")]
    monkeypatch.setattr(db.asyncpg, "connect", connect)
    monkeypatch.setattr(db, "migration_steps", lambda _: steps)
    with pytest.raises(ValueError, match="Synthetic migration failure"):
        await db.migrate("synthetic", Path("unused"))
    assert connection.ledger == {} and connection.statements == [] and connection.closed
    steps[1] = (steps[1][0], steps[1][1], "synthetic index")
    await db.migrate("synthetic", Path("unused"))
    assert len(connection.ledger) == 2
    await db.migrate("synthetic", Path("unused"))
    assert connection.statements.count("synthetic create") == 1
    before = copy.deepcopy(connection.ledger)
    steps[0] = (steps[0][0], "c" * 64, steps[0][2])
    with pytest.raises(RuntimeError, match="checksum"):
        await db.migrate("synthetic", Path("unused"))
    assert connection.ledger == before
    steps.clear()
    with pytest.raises(RuntimeError, match="Unknown migration"):
        await db.migrate("synthetic", Path("unused"))
    assert connection.ledger == before
