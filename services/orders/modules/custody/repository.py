"""Durable local custody receipts with one atomic private record and outbox write."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import timezone
from pathlib import Path

from .domain import CustodyError, check_facts, due_actions, transition, validate


class Custody:
    def __init__(self, database, provider, clock):
        self.database = database
        self.provider = provider
        self.clock = clock
        with self.connect() as db:
            db.executescript((Path(__file__).parent / "migrations" / "L24_0001_custody.sql").read_text())

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, context, command):
        validate(command, context)
        encoded = json.dumps(command, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode()) > 16384:
            raise CustodyError("invalid")
        with self.provider.current(context, command["subject_id"], timeout_seconds=2) as facts:
            if command["action"] not in facts.permitted_actions:
                raise CustodyError("denied")
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT request,result FROM l24_custody_operations WHERE operation_id=?",
                    (command["operation_id"],),
                ).fetchone()
                if existing:
                    if existing[0] != encoded:
                        raise CustodyError("conflict")
                    return json.loads(existing[1])
                check_facts(command, facts)
                row = db.execute("SELECT body FROM l24_custody_records WHERE order_id=?",
                                 (command["subject_id"],)).fetchone()
                now = self.clock()
                if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
                    raise CustodyError("unavailable")
                result = transition(command, facts, json.loads(row[0]) if row else None, now)
                result.update({key: command[key] for key in (
                    "schema_version", "operation_id", "subject_id", "watch_id", "actor_id",
                    "organization_id", "expected_revision", "source_revision", "quote_id",
                    "quote_revision", "policy_revision", "watch_revision",
                )})
                result["watch_revision"] = facts.watch_revision
                body = json.dumps(result, ensure_ascii=False)
                db.execute("INSERT INTO l24_custody_records VALUES (?,?) ON CONFLICT(order_id) "
                           "DO UPDATE SET body=excluded.body", (facts.order_id, body))
                db.execute("INSERT INTO l24_custody_operations VALUES (?,?,?,?,?)",
                           (command["operation_id"], facts.order_id, result["revision"], encoded, body))
                event = {"schema_version": "custody.changed.v1", "operation_id": command["operation_id"],
                         "subject_id": facts.order_id, "revision": result["revision"]}
                db.execute("INSERT INTO l24_custody_outbox VALUES (?,?)",
                           (command["operation_id"], json.dumps(event)))
                return result

    def lookup(self, context, order_id, operation_id):
        with self.provider.current(context, order_id, timeout_seconds=2):
            with self.connect() as db:
                row = db.execute("SELECT result FROM l24_custody_operations WHERE operation_id=?",
                                 (operation_id,)).fetchone()
            if not row or json.loads(row[0])["subject_id"] != order_id:
                raise CustodyError("denied")
            return json.loads(row[0])

    def read(self, context, order_id):
        with self.provider.current(context, order_id, timeout_seconds=2) as facts:
            with self.connect() as db:
                row = db.execute("SELECT body FROM l24_custody_records WHERE order_id=?", (order_id,)).fetchone()
            if not row:
                return None
            result = json.loads(row[0])
            result["due_actions"] = due_actions(result, facts, self.clock())
            result["current"] = {
                "watch_id": facts.watch_id, "watch_revision": facts.watch_revision,
                "source_revision": facts.source_revision, "quote_id": facts.quote_id,
                "quote_revision": facts.quote_revision, "policy_revision": facts.policy_revision,
                "actor_id": context.actor_id, "organization_id": context.organization_id,
            }
            return result

    def history(self, context, order_id, offset=0, limit=25):
        if type(offset) is not int or type(limit) is not int or not 0 <= offset <= 1000000 or not 1 <= limit <= 100:
            raise CustodyError("invalid")
        with self.provider.current(context, order_id, timeout_seconds=2):
            with self.connect() as db:
                db.execute("BEGIN")
                total = db.execute("SELECT count(*) FROM l24_custody_operations WHERE order_id=?", (order_id,)).fetchone()[0]
                rows = db.execute("SELECT result FROM l24_custody_operations WHERE order_id=? "
                                  "ORDER BY revision DESC LIMIT ? OFFSET ?", (order_id, limit, offset)).fetchall()
            items = []
            for row in rows:
                value = json.loads(row[0])
                items.append({key: value[key] for key in (
                    "operation_id", "revision", "state", "held", "buyer_received_at", "dispute_deadline",
                )})
            return {"subject_id": order_id, "items": items, "total": total, "offset": offset, "limit": limit}
