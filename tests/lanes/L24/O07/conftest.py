"""Synthetic canonical journal fixture; no connected financial proof."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timedelta
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / "services/orders/modules/releases"
spec = importlib.util.spec_from_file_location("o07_releases", MODULE / "__init__.py",
                                            submodule_search_locations=[str(MODULE)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from o07_releases.contracts import Command, Context, Snapshot, Operation  # noqa: E402
from o07_releases.service import Denied, Releases  # noqa: E402

DATA = json.loads((ROOT / "packages/contracts-orders/releases/fixtures.json").read_text())
NOW = datetime.fromisoformat(DATA["now"].replace("Z", "+00:00"))


class JournalFixture:
    """Persist only test data. Represents the sole journal, never a runtime fallback."""
    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS source (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT);
            CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, command TEXT, result TEXT);
            CREATE TABLE IF NOT EXISTS outbox (order_id TEXT PRIMARY KEY, operation_id TEXT UNIQUE, recipient TEXT);
            CREATE TABLE IF NOT EXISTS inbox (operation_id TEXT PRIMARY KEY, outcome TEXT);
        """)
        if not self.db.execute("SELECT 1 FROM source").fetchone():
            self.set_source(Snapshot.model_validate(DATA["source"]))
        self.allowed = True
        self.lose_response = False
        self.now = NOW
        self.before_reserve = None
        self.outcome = "paid_out"

    @property
    def source(self):
        return Snapshot.model_validate_json(self.db.execute("SELECT body FROM source").fetchone()[0])

    def set_source(self, source):
        self.db.execute("INSERT OR REPLACE INTO source VALUES(1,?)", (source.model_dump_json(),))

    def authorize(self, context, order_id):
        if not self.allowed or context.actor_id != UUID(DATA["command"]["actor_id"]) or (
            context.organization_id != self.source.organization_id or order_id != self.source.subject_id
        ):
            raise Denied()

    async def current(self, context, order_id):
        self.authorize(context, order_id)
        return self.source

    async def reserve(self, command, decide):
        if self.before_reserve:
            self.before_reserve()
            self.before_reserve = None
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.authorize(command, command.subject_id)
            prior = self.db.execute("SELECT command,result FROM operations WHERE id=?",
                                    (str(command.operation_id),)).fetchone()
            if prior:
                if Command.model_validate_json(prior[0]) != command:
                    raise Denied()
                result = Operation.model_validate_json(prior[1])
            else:
                source = self.source
                missing = decide(source, self.now, command)
                result = Operation(
                    **command.model_dump(), state="denied" if missing else "pending",
                    revision=source.revision + 1, missing=missing,
                    pending_reason=None if missing else "transfer_pending",
                    next_actor="operator", responsible_operator_id=source.responsible_operator_id,
                    responsibility_revision=source.responsibility_revision,
                    next_action="review_conditions" if missing else "reconcile_transfer", next_review_at=self.now + timedelta(hours=24),
                    gross_minor=source.principal_minor, fee_minor=source.business_fee_minor,
                    net_minor=source.principal_minor-source.business_fee_minor,
                )
                if not missing:
                    self.db.execute("INSERT INTO outbox VALUES(?,?,?)", (
                        str(command.subject_id), str(command.operation_id), str(command.recipient_id)))
                    self.set_source(source.model_copy(update={
                        "revision": source.revision+1, "active_release_operation_id": command.operation_id}))
                self.db.execute("INSERT INTO operations VALUES(?,?,?)", (
                    str(command.operation_id), command.model_dump_json(), result.model_dump_json()))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        if self.lose_response:
            self.lose_response = False
            raise TimeoutError()
        return result

    async def lookup(self, context, operation_id):
        row = self.db.execute("SELECT result FROM operations WHERE id=?", (str(operation_id),)).fetchone()
        if not row:
            raise Denied()
        result = Operation.model_validate_json(row[0])
        self.authorize(context, result.subject_id)
        if context.actor_id != result.actor_id or context.organization_id != result.organization_id:
            raise Denied()
        return result

    async def reconcile(self, context, operation_id):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result = await self.lookup(context, operation_id)
            if result.state == "pending" and self.source.hold_state != "clear":
                result = result.model_copy(update={"pending_reason": "response_unknown",
                                                  "next_action": "reconcile_transfer"})
                self.db.execute("UPDATE operations SET result=? WHERE id=?",
                                (result.model_dump_json(), str(operation_id)))
                self.db.execute("COMMIT")
                return result
            if result.state == "pending":
                self.db.execute("INSERT OR IGNORE INTO inbox VALUES(?,?)", (str(operation_id), self.outcome))
                outcome = self.db.execute("SELECT outcome FROM inbox WHERE operation_id=?",
                                          (str(operation_id),)).fetchone()[0]
                result = result.model_copy(update={
                    "state": "paid_out" if outcome == "paid_out" else "pending",
                    "pending_reason": None if outcome == "paid_out" else "transfer_failed",
                    "revision": result.revision+1,
                    "next_action": "complete" if outcome == "paid_out" else "reconcile_transfer",
                })
                self.db.execute("UPDATE operations SET result=? WHERE id=?",
                                (result.model_dump_json(), str(operation_id)))
            self.db.execute("COMMIT")
            return result
        except Exception:
            self.db.execute("ROLLBACK")
            raise


@pytest.fixture
def journal(tmp_path):
    value = JournalFixture(tmp_path / "journal.sqlite")
    yield value
    value.db.close()


@pytest.fixture
def command():
    return Command.model_validate(DATA["command"])


@pytest.fixture
def context(command):
    return Context(actor_id=command.actor_id, organization_id=command.organization_id)


@pytest.fixture
def service(journal):
    return Releases(journal, clock=lambda: NOW)
