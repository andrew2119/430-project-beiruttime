"""Durable local commands; current facts are supplied by the owning providers."""
import copy
import hashlib
import json
import re
import sqlite3
from queue import Queue, Empty
from threading import BoundedSemaphore, Thread
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import importlib.util

_contract = Path(__file__).resolve().parents[4] / "packages/contracts-service/enlargement/v1.py"
_spec = importlib.util.spec_from_file_location("enlargement_contract", _contract)
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

class Rejected(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def instant(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Rejected("invalid_time")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Rejected("invalid_time") from None


def measurement(value, unit):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9])?", value) or unit not in ("cm", "mm"):
        raise Rejected("measurement")
    mm = Decimal(value) * (10 if unit == "cm" else 1)
    if not 80 <= mm <= 350:
        raise Rejected("measurement")
    return str(mm.normalize())


def bounded_text(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 1000:
        raise Rejected("required_detail")
    return value


class Service:
    def __init__(self, database, current, clock=lambda: datetime.now(timezone.utc), dependency_timeout=2):
        self.database, self.current, self.clock = database, current, clock
        if not 0.01 <= dependency_timeout <= 2:
            raise ValueError("dependency_timeout")
        self.dependency_timeout = dependency_timeout
        self.dependency_slot = BoundedSemaphore(1)
        with self.connect() as db:
            db.executescript((Path(__file__).parent / "migrations/L23_0001_enlargement.sql").read_text())

    def connect(self):
        return sqlite3.connect(self.database, timeout=2)

    def provider(self, actor, body):
        if not self.dependency_slot.acquire(blocking=False):
            raise Rejected("unavailable")
        result = Queue(maxsize=1)
        def fetch():
            try:
                facts = copy.deepcopy(self.current(actor, body))
                if len(json.dumps(facts).encode()) > 65536:
                    raise ValueError("response_budget")
                result.put((True, facts))
            except Exception:
                result.put((False, None))
            finally:
                self.dependency_slot.release()
        Thread(target=fetch, daemon=True).start()
        try:
            okay, facts = result.get(timeout=self.dependency_timeout)
        except Empty:
            raise Rejected("unavailable") from None
        if not okay:
            raise Rejected("unavailable")
        return facts

    def facts(self, actor, command):
        try:
            facts = self.provider(actor, command.model_dump())
        except (TimeoutError, ConnectionError):
            raise Rejected("unavailable") from None
        if not facts or not facts.get("active") or not facts.get("authorized"):
            raise Rejected("denied")
        if (facts.get("actor_id") != actor or facts.get("organization_id") != command.organization_id
                or facts.get("watch_id") != command.watch_id):
            raise Rejected("denied")
        if facts.get("source_revision") != command.source_revision:
            raise Rejected("stale")
        if not facts.get("commitment_current") or not facts.get("capability_current"):
            raise Rejected("unavailable")
        return facts

    def read(self, actor, request_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM l23_enlargement_records WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise Rejected("denied")
        record = json.loads(row[0])
        try:
            facts = self.provider(actor, {"kind": "read", "request_id": request_id,
                "watch_id": record["watch_id"], "organization_id": record["organization_id"]})
        except (TimeoutError, ConnectionError):
            raise Rejected("unavailable") from None
        if not facts or not all(facts.get(key) for key in ("active", "authorized")) or any(
            facts.get(key) != value for key, value in (("actor_id", actor),
                ("buyer_id", record["subject_id"]), ("organization_id", record["organization_id"]),
                ("watch_id", record["watch_id"]))):
            raise Rejected("denied")
        role = facts.get("role")
        if role not in ("buyer", "assessor", "staff", "quality") or (role == "buyer" and actor != record["subject_id"]) or (role != "buyer" and not facts.get("assignment_current")):
            raise Rejected("denied")
        allowed = [kind for kind, rule in contract.OPERATIONS.items()
            if rule["permission"] == role and record["state"] in rule["from"]
            and (role == "buyer" and actor == record["subject_id"] or role != "buyer" and facts.get("assignment_current"))]
        return {**record, "allowed_operations": allowed}

    def execute(self, actor, raw):
        command = contract.Command.model_validate(raw)
        if len(json.dumps(command.payload).encode()) > 16384:
            raise Rejected("too_large")
        digest = hashlib.sha256(json.dumps(command.model_dump(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            facts = self.facts(actor, command)
            row = db.execute("SELECT body FROM l23_enlargement_records WHERE id=?", (command.request_id,)).fetchone()
            record = json.loads(row[0]) if row else None
            if record and (record["subject_id"] != facts["buyer_id"] or record["organization_id"] != command.organization_id or record["watch_id"] != command.watch_id):
                raise Rejected("denied")
            role = contract.OPERATIONS[command.kind]["permission"]
            if facts.get("role") != role or (role == "buyer" and actor != facts["buyer_id"]):
                raise Rejected("denied")
            if role != "buyer" and not facts.get("assignment_current"):
                raise Rejected("denied")
            receipt = db.execute("SELECT digest,actor,result FROM l23_enlargement_receipts WHERE operation=?", (command.operation_id,)).fetchone()
            if receipt:
                if receipt[:2] != (digest, actor):
                    raise Rejected("operation_conflict")
                return json.loads(receipt[2])
            if (record["revision"] if record else 0) != command.expected_revision:
                raise Rejected("stale")
            if (record["state"] if record else None) not in contract.OPERATIONS[command.kind]["from"]:
                raise Rejected("state")
            now = self.clock()
            if now.tzinfo is None:
                raise Rejected("invalid_time")
            result = copy.deepcopy(record) if record else {
                "schema_version": "enlargement.v1", "request_id": command.request_id,
                "subject_id": facts["buyer_id"], "watch_id": command.watch_id,
                "organization_id": command.organization_id,
            }
            p = command.payload
            state = contract.OPERATIONS[command.kind]["to"]
            if command.kind == "request":
                if set(p) != {"measurement", "unit", "method", "source", "target", "choice"} or p["choice"] not in ("links", "strap", "clasp"):
                    raise Rejected("scope")
                result["request"] = {**p, "measurement_mm": measurement(p["measurement"], p["unit"])}
                for key in ("method", "source", "target"):
                    bounded_text(p[key])
            elif command.kind == "assess":
                if set(p) != {"parts", "target", "limitations", "quote_id", "quote_revision", "total_minor", "expires_at", "terms_revision"}:
                    raise Rejected("scope")
                if not isinstance(p["total_minor"], int) or isinstance(p["total_minor"], bool) or not 0 <= p["total_minor"] <= 10**12:
                    raise Rejected("money")
                if any(type(p[key]) is not int or p[key] < 1 for key in ("quote_revision", "terms_revision")):
                    raise Rejected("quote")
                bounded_text(p["quote_id"])
                quote = facts.get("quote")
                if not isinstance(quote, dict) or any(
                    type(quote.get(key)) is not int or not 0 <= quote[key] <= 10**12
                    for key in ("base_minor", "buyer_fee_minor", "business_fee_minor", "total_minor")
                ):
                    raise Rejected("money")
                if not quote or any(quote.get(k) != p[k] for k in ("quote_id", "quote_revision", "total_minor", "expires_at", "terms_revision")) or quote.get("currency") != "USD" or quote.get("buyer_id") != facts["buyer_id"] or quote.get("request_id") != command.request_id:
                    raise Rejected("quote")
                if quote.get("base_minor") != p["total_minor"] or quote.get("business_fee_minor") != (p["total_minor"] * 5 + 50) // 100 or quote.get("buyer_fee_minor") != 0:
                    raise Rejected("quote")
                result["economics"] = {key: quote[key] for key in ("quote_id", "quote_revision", "currency", "base_minor", "buyer_fee_minor", "business_fee_minor", "total_minor", "terms_revision")}
                if instant(p["expires_at"]) <= now:
                    raise Rejected("expired")
                bounded_text(p["target"]); bounded_text(p["limitations"])
                if not isinstance(p["parts"], list) or not 1 <= len(p["parts"]) <= 20:
                    raise Rejected("parts")
                available = facts.get("parts", {})
                part_ids = set()
                for part in p["parts"]:
                    if set(part) != {"id", "revision", "kind", "status", "quantity"} or part != available.get(part["id"]):
                        raise Rejected("parts")
                    if type(part["revision"]) is not int or part["revision"] < 1:
                        raise Rejected("parts")
                    bounded_text(part["id"])
                    if part["id"] in part_ids:
                        raise Rejected("parts")
                    part_ids.add(part["id"])
                    if part["kind"] not in ("links", "strap", "clasp") or part["status"] not in ("supplied", "ordered", "available", "unavailable") or type(part["quantity"]) is not int or not 1 <= part["quantity"] <= 100:
                        raise Rejected("parts")
                for previous in ("accepted", "work", "work_revision", "quality"):
                    result.pop(previous, None)
                result["assessment"] = copy.deepcopy(p)
                lines = quote.get("lines")
                terms = quote.get("terms")
                if not isinstance(lines, list) or not 1 <= len(lines) <= 50 or not isinstance(terms, dict) or set(terms) != {"en", "ar"}:
                    raise Rejected("quote")
                ids = set()
                for line in lines:
                    if set(line) != {"id", "label_en", "label_ar", "amount_minor"} or line["id"] in ids or type(line["amount_minor"]) is not int or not 0 <= line["amount_minor"] <= 10**12:
                        raise Rejected("quote")
                    for key in ("id", "label_en", "label_ar"):
                        bounded_text(line[key])
                    ids.add(line["id"])
                if sum(line["amount_minor"] for line in lines) != p["total_minor"]:
                    raise Rejected("quote")
                bounded_text(terms["en"]); bounded_text(terms["ar"])
                result["quote_lines"] = copy.deepcopy(lines)
                result["quote_terms"] = copy.deepcopy(terms)
                result["assessor_id"] = actor
                if any(part["status"] in ("ordered", "unavailable") for part in p["parts"]):
                    state = "waiting"
            elif command.kind == "accept":
                assessment = result["assessment"]
                if p != {"quote_id": assessment["quote_id"], "quote_revision": assessment["quote_revision"], "terms_revision": assessment["terms_revision"], "accepted_line_ids": [line["id"] for line in result["quote_lines"]]}:
                    raise Rejected("quote")
                if now >= instant(assessment["expires_at"]):
                    raise Rejected("expired")
                if not facts.get("quote_current") or not facts.get("explicit_lines_accepted"):
                    raise Rejected("quote")
                result["accepted"] = {**p, "at": now.isoformat().replace("+00:00", "Z")}
            elif command.kind == "work":
                if "accepted" not in result or not all(facts.get(k) for k in ("accepted_scope_current", "custody_current", "paid_held", "approval_current", "independence_current")) or facts.get("incident_open") is not False:
                    raise Rejected("work_held")
                required = result["assessment"]["parts"]
                current_parts = facts.get("parts", {})
                def sufficient(part):
                    current = current_parts.get(part["id"], {})
                    return (current.get("status") in ("supplied", "available")
                        and current.get("revision") == part["revision"]
                        and current.get("kind") == part["kind"]
                        and type(current.get("quantity")) is int
                        and current["quantity"] >= part["quantity"])
                missing = any(not sufficient(part) for part in required)
                if missing:
                    state = "waiting"
                    result.pop("quality", None)
                else:
                    if set(p) != {"performed", "part_ids", "completed_line_ids"} or sorted(p["completed_line_ids"]) != sorted(result["accepted"]["accepted_line_ids"]) or sorted(p["part_ids"]) != sorted(part["id"] for part in required):
                        raise Rejected("work_missing")
                    bounded_text(p["performed"])
                    result.pop("quality", None)
                    result["work"] = copy.deepcopy(p)
                    result["work_revision"] = command.expected_revision + 1
            elif command.kind == "fit":
                if not facts.get("approver_id") or not facts.get("independence_current") or actor == result["assessor_id"] or actor == facts.get("approver_id") or not facts.get("quality_current") or not facts.get("custody_current") or not facts.get("accepted_scope_current") or facts.get("incident_open") is not False:
                    raise Rejected("denied")
                if set(p) != {"fit", "tests", "returned_parts", "passed", "work_revision"} or p["work_revision"] != result["work_revision"] or type(p["passed"]) is not bool:
                    raise Rejected("quality")
                for key in ("fit", "tests", "returned_parts"):
                    bounded_text(p[key])
                result["quality"] = copy.deepcopy(p)
                state = "fit_recorded" if p["passed"] else "rework"
            waiting = state == "waiting"
            held = state in ("waiting", "rework")
            result.update(operation_id=command.operation_id, actor_id=actor, expected_revision=command.expected_revision,
                source_revision=command.source_revision, revision=command.expected_revision + 1, state=state,
                pending_reason="parts" if waiting else "rework" if held else None, next_actor="business" if waiting else "buyer" if state == "assessed" else "business",
                next_review_at=facts.get("next_review_at") if held else None)
            if held and (not result["next_review_at"] or instant(result["next_review_at"]) <= now):
                raise Rejected("review_required")
            if held:
                operator = bounded_text(facts.get("responsible_operator_id"))
                action = facts.get("next_action")
                if not isinstance(action, dict) or set(action) != {"en", "ar"}:
                    raise Rejected("review_required")
                for text in action.values():
                    bounded_text(text)
                since = instant(record["waiting_since"]) if record and record["state"] in ("waiting", "rework") else now
                if instant(result["next_review_at"]) > now + timedelta(hours=24):
                    raise Rejected("review_required")
                result.update(responsible_operator_id=operator, next_action=copy.deepcopy(action),
                    waiting_since=since.isoformat().replace("+00:00", "Z"),
                    first_response_due_at=(since + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
                    escalation_at=(since + timedelta(hours=48)).isoformat().replace("+00:00", "Z"))
            else:
                for key in ("responsible_operator_id", "next_action", "waiting_since", "first_response_due_at", "escalation_at"):
                    result.pop(key, None)
            serialized = json.dumps(result, sort_keys=True)
            db.execute("INSERT OR REPLACE INTO l23_enlargement_records VALUES (?,?)", (command.request_id, serialized))
            db.execute("INSERT INTO l23_enlargement_receipts VALUES (?,?,?,?)", (command.operation_id, digest, actor, serialized))
            event = json.dumps({"schema_version": "enlargement.changed.v1", "operation_id": command.operation_id, "request_id": command.request_id, "revision": result["revision"], "state": state})
            db.execute("INSERT INTO l23_enlargement_outbox VALUES (?,?)", (command.operation_id, event))
            return result
