"""Route recovery with local durable persistence and bounded source substitutes."""

import hashlib
import json
import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from uuid import UUID

import pytest
from bt_contracts_core.errors import PublicError

import test_current
from test_current import ROOT, bind, contract, load


class Store:
    """Only the decision repository statements are supported by this substitute."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, record TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (payload TEXT)")

    def rows(self):
        rows = [json.loads(row[0]) for row in self.db.execute("SELECT record FROM decisions")]
        for row in rows:
            for key in ("id", "request_id", "actor_id", "brand_id"):
                row[key] = UUID(row[key])
            if row["confirmed_at"]:
                row["confirmed_at"] = datetime.fromisoformat(row["confirmed_at"])
        return rows

    def save(self, row):
        payload = json.dumps(row, default=str)
        self.db.execute("INSERT OR REPLACE INTO decisions VALUES (?, ?)", (str(row["id"]), payload))
        self.db.commit()
        return dict(row)

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def fetchrow(self, sql, *args):
        if sql.startswith("INSERT INTO"):
            keys = ("id", "request_id", "request_revision", "actor_id", "brand_id", "operation_key", "digest", "intent", "recovery")
            return self.save({**dict(zip(keys, args)), "status": "pending", "bindings": None,
                              "code": None, "confirmed_at": None})
        rows = self.rows()
        if "actor_id=$1 AND operation_key=$2" in sql:
            return next((r for r in rows if (r["actor_id"], r["operation_key"]) == args), None)
        row = next((r for r in rows if r["id"] == args[0]), None)
        if sql.startswith("SELECT"):
            return row
        if sql.startswith("UPDATE") and row:
            if "SET recovery=" in sql:
                row.update(recovery=args[1])
            elif "status='denied'" in sql:
                row.update(status="denied", code=args[1])
            elif "confirmed_at=" in sql:
                row.update(status=args[1], confirmed_at=datetime.now(timezone.utc))
            else:
                raise AssertionError(sql)
            return self.save(row)
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        assert "status IN ('pending','approved','rejected')" in sql
        return any(r["request_id"] == args[0] and r["request_revision"] == args[1]
                   and r["status"] in ("pending", "approved", "rejected") for r in self.rows())

    async def execute(self, sql, *args):
        assert "SET bindings=" in sql
        row = next(r for r in self.rows() if r["id"] == args[0])
        assert row["status"] == "pending" and row["bindings"] is None
        row["bindings"] = args[1]
        self.save(row)


def install(monkeypatch, name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def authority(monkeypatch):
    return test_current.authority.__wrapped__(monkeypatch)


@pytest.fixture
def route_setup(monkeypatch, tmp_path, authority):
    sample = contract.fixture()
    row = {k: UUID(v) if k in ("id", "brand_id", "buyer_id") else v for k, v in sample["row"].items()}
    row.update(watch_id=UUID(int=20), recovery_operator_id=UUID(int=21))
    actor = UUID(sample["approver_id"])
    path = tmp_path / "decisions.sqlite"
    bindings = bind(authority, sample)
    body_module = load("decision_body", "packages/contracts-catalog/request-drafts/v2.py")
    event_module = load("decision_event", "packages/contracts-catalog/brand-decisions/v1.py")
    install(monkeypatch, "bt_contracts.catalog.request_drafts.v2", Decision=body_module.Decision)
    install(monkeypatch, "bt_contracts.catalog.brand_decisions.v1", DecisionEvent=event_module.DecisionEvent)
    install(monkeypatch, "service_app.catalog_dependencies", principal=None)
    install(monkeypatch, "service_app.configuration", digest=lambda value: hashlib.sha256(
        json.dumps(value, sort_keys=True).encode()).hexdigest())
    install(monkeypatch, "service_app.customization", current=None, readable=None, active_brand=None,
            service=None, decode=lambda value: json.loads(value) if isinstance(value, str) else value)
    package = install(monkeypatch, "decision_routes", authority=authority)
    package.__path__ = [str(ROOT / "services/catalog/modules/brand-decisions")]

    def start():
        pool = Store(path)
        routes = load("decision_routes.routes", "services/catalog/modules/brand-decisions/routes.py")

        async def current(*args, **kwargs):
            return row, None

        async def approver(*args):
            return SimpleNamespace(actor=SimpleNamespace(subject_id=actor))

        async def readable(*args):
            return None

        @asynccontextmanager
        async def transaction(pool, **kwargs):
            yield pool

        async def enqueue(tx, event, destinations):
            tx.db.execute("INSERT INTO events VALUES (?)", (event.model_dump_json(),))
            tx.db.commit()

        for key, value in dict(current=current, approver=approver, readable=readable,
                               unit_of_work=transaction, enqueue=enqueue).items():
            monkeypatch.setattr(routes, key, value)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)),
                                  headers={"Idempotency-Key": "decision-1"},
                                  state=SimpleNamespace(request_id="decision-test"))
        return routes, request, pool

    async def sources(*args):
        return sample["values"]

    monkeypatch.setattr(authority, "current", sources)
    monkeypatch.setattr(authority, "bind", lambda *args: bindings)
    body = body_module.Decision(expected_revision=1, decision="approve", reason="Scope reviewed",
                               **sample["intent"])
    return start, body, authority, row


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_lost_response_restart_and_duplicates(route_setup, monkeypatch, decision):
    start, body, authority, row = route_setup
    body = body.model_copy(update={"decision": decision})
    routes, request, pool = start()
    remote = {}
    calls = []

    async def response(*args, **kwargs):
        command = kwargs["json"]
        stored = pool.rows()
        assert len(stored) == 1 and stored[0]["status"] == "pending"
        assert stored[0]["bindings"] is not None
        calls.append(command)
        key = command["operation_id"]
        if args[3].endswith("prepare"):
            return {**command, "status": "prepared"}
        remote[key] = {**command, "status": "succeeded", "current": True}
        return None

    monkeypatch.setattr(authority, "service_request", response)
    with pytest.raises(PublicError) as error:
        await routes.decide(row["id"], body, request)
    assert error.value.status >= 500
    operation_id = pool.rows()[0]["id"]
    pending = await routes.operation(operation_id, request)
    assert contract.CurrentOperation.model_validate(pending).status == "pending"
    assert pending["confirmed_at"] is None
    assert pool.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    pool.db.close()

    routes, request, pool = start()
    assert (await routes.operation(operation_id, request)) == pending
    with pytest.raises(PublicError) as conflict:
        await routes.decide(row["id"], body.model_copy(update={"reason": "Different reason"}), request)
    assert conflict.value.code == "idempotency_conflict"
    assert len(calls) == 2

    async def recovered(*args, **kwargs):
        command = kwargs["json"]
        assert command == calls[0]
        if args[3].endswith("prepare"):
            return {**command, "status": "succeeded"}
        return remote[command["operation_id"]]

    monkeypatch.setattr(authority, "service_request", recovered)
    confirmed = await routes.reconcile(operation_id, request)
    expected = "approved" if decision == "approve" else "rejected"
    assert contract.CurrentOperation.model_validate(confirmed).status == expected
    assert confirmed["confirmed_at"] is not None
    assert await routes.decide(row["id"], body, request) == confirmed
    assert await routes.operation(operation_id, request) == confirmed
    assert len(pool.rows()) == 1
    assert pool.db.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    pool.db.close()


@pytest.mark.asyncio
async def test_denied_resume_and_lookup_validate(route_setup, monkeypatch):
    start, body, authority, row = route_setup
    routes, request, pool = start()

    async def denied(*args, **kwargs):
        return {"operation_id": kwargs["json"]["operation_id"], "status": "denied"}

    monkeypatch.setattr(authority, "service_request", denied)
    result = await routes.decide(row["id"], body, request)
    parsed = contract.CurrentOperation.model_validate(result)
    assert parsed.status == "denied" and parsed.code == "grant_denied"
    assert parsed.confirmed_at is None
    assert await routes.operation(parsed.id, request) == result
    assert pool.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    pool.db.close()


@pytest.mark.asyncio
async def test_recovery_deadlines_survive_restart(route_setup, monkeypatch):
    from datetime import timedelta
    start, body, authority, row = route_setup
    routes, request, pool = start()

    async def lost(*args, **kwargs):
        return None

    monkeypatch.setattr(authority, "service_request", lost)
    with pytest.raises(PublicError):
        await routes.decide(row["id"], body, request)
    stored = pool.rows()[0]
    original = await routes.operation(stored["id"], request)
    pool.db.close()
    routes, request, pool = start()
    assert await routes.operation(stored["id"], request) == original
    review = datetime.fromisoformat(original["next_review_at"])
    escalation = datetime.fromisoformat(original["escalate_at"])
    for deadline, before, due in (
        (review, "reconcile_operation", "respond_to_operation"),
        (escalation, "respond_to_operation", "escalate_operation"),
    ):
        for offset, action in ((-1, before), (0, due), (1, due)):
            result = routes.dto(pool.rows()[0], now=deadline + timedelta(seconds=offset))
            parsed = contract.CurrentOperation.model_validate(result)
            assert parsed.next_action == action
            assert parsed.next_actor == row["recovery_operator_id"]
            assert parsed.watch_id == row["watch_id"]
            assert parsed.status == parsed.state == "pending"
            assert parsed.operation_id == parsed.id
            assert parsed.next_review_at.isoformat() == original["next_review_at"]
            assert parsed.confirmed_at is None
    pool.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["watch_id", "recovery_operator_id"])
async def test_missing_recovery_binding_prevents_remote_call(route_setup, monkeypatch, missing):
    start, body, authority, row = route_setup
    routes, request, pool = start()
    row.pop(missing)

    async def unexpected(*args, **kwargs):
        pytest.fail("No remote request before durable recovery assignment")

    monkeypatch.setattr(authority, "service_request", unexpected)
    with pytest.raises(PublicError) as error:
        await routes.decide(row["id"], body, request)
    assert error.value.code == "recovery_unavailable"
    assert not pool.rows()
    pool.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["approved", "rejected", "pending"])
@pytest.mark.parametrize("retained_revisions", [False, True])
async def test_legacy_results_remain_readable(route_setup, monkeypatch, status, retained_revisions):
    start, body, authority, row = route_setup
    routes, request, pool = start()

    async def lost(*args, **kwargs):
        return None

    monkeypatch.setattr(authority, "service_request", lost)
    with pytest.raises(PublicError):
        await routes.decide(row["id"], body, request)
    stored = pool.rows()[0]
    stored.update(recovery=None, status=status,
                  confirmed_at=datetime.now(timezone.utc) if status != "pending" else None)
    if status != "pending":
        legacy = json.loads(stored["bindings"])
        if not retained_revisions:
            legacy.pop("consent_revision")
            legacy.pop("assignment_revision")
        legacy.pop("watch_id")
        stored["bindings"] = json.dumps(legacy)
    pool.save(stored)
    result = await routes.operation(stored["id"], request)
    parsed = contract.CurrentOperation.model_validate(result)
    assert parsed.status == status
    assert parsed.operation_id == stored["id"]
    assert parsed.watch_id is None
    assert parsed.execution_authority is False
    if status == "pending":
        assert parsed.next_action == "restore_recovery"
        assert parsed.next_actor == row["recovery_operator_id"]
    else:
        assert parsed.confirmed_at is not None
        assert parsed.next_action is None
    pool.db.close()


@pytest.mark.asyncio
async def test_assigned_recovery_repairs_legacy_pending_without_deciding(route_setup, monkeypatch):
    from bt_contracts_core.errors import AccessDenied
    start, body, authority, row = route_setup
    routes, request, pool = start()

    async def lost(*args, **kwargs):
        return None

    monkeypatch.setattr(authority, "service_request", lost)
    with pytest.raises(PublicError):
        await routes.decide(row["id"], body, request)
    stored = pool.rows()[0]
    stored["recovery"] = None
    pool.save(stored)
    acting = row["recovery_operator_id"]

    async def principal(*args):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=acting))

    async def active(*args):
        return None

    def scope(*args):
        assert args[1:] == ("business.jobs.write", row["brand_id"])

    async def unexpected(*args, **kwargs):
        pytest.fail("Recovery cannot contact approval authority")

    monkeypatch.setattr(routes, "principal", principal)
    monkeypatch.setattr(routes, "active_brand", active)
    monkeypatch.setattr(routes, "require_scope", scope)
    monkeypatch.setattr(authority, "service_request", unexpected)
    result = await routes.recovery_followup(stored["id"], request)
    assert result["status"] == "pending"
    assert result["actor_id"] == str(stored["actor_id"])
    assert result["next_actor"] == str(acting)
    assert result["next_action"] == "escalate_operation"
    metadata = json.loads(pool.rows()[0]["recovery"])
    assert metadata["responded_at"] == metadata["escalated_at"]
    assert await routes.recovery_followup(stored["id"], request) == result
    pool.db.close()
    routes, request, pool = start()
    monkeypatch.setattr(routes, "principal", principal)
    monkeypatch.setattr(routes, "active_brand", active)
    monkeypatch.setattr(routes, "require_scope", scope)
    assert await routes.operation(stored["id"], request) == result
    async def operator_approver(*args):
        return await principal()

    monkeypatch.setattr(routes, "approver", operator_approver)
    with pytest.raises(AccessDenied):
        await routes.reconcile(stored["id"], request)
    row["revision"] = 2
    with pytest.raises(PublicError) as stale:
        await routes.recovery_followup(stored["id"], request)
    assert stale.value.code == "stale_scope"
    row["revision"] = 1
    acting = UUID(int=99)
    with pytest.raises(AccessDenied):
        await routes.recovery_followup(stored["id"], request)
    assert pool.rows()[0]["actor_id"] == stored["actor_id"]
    assert pool.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    pool.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", ["currency", "consent", "assignment", "watch", "changed_watch"])
async def test_retained_pending_requires_current_bindings(route_setup, monkeypatch, legacy):
    start, body, authority, row = route_setup
    routes, request, pool = start()

    async def lost(*args, **kwargs):
        return None

    monkeypatch.setattr(authority, "service_request", lost)
    with pytest.raises(PublicError):
        await routes.decide(row["id"], body, request)
    stored = pool.rows()[0]
    bindings = json.loads(stored["bindings"])
    if legacy == "currency":
        bindings["currency"] = "LBP"
    elif legacy == "changed_watch":
        bindings["watch_id"] = str(UUID(int=99))
    else:
        bindings.pop({"consent": "consent_revision", "assignment": "assignment_revision",
                      "watch": "watch_id"}[legacy])
    stored["bindings"] = json.dumps(bindings)
    pool.save(stored)

    async def unexpected(*args, **kwargs):
        pytest.fail("Retained incomplete scope cannot reach authority")

    monkeypatch.setattr(authority, "service_request", unexpected)
    with pytest.raises(PublicError) as error:
        await routes.reconcile(stored["id"], request)
    assert error.value.status == 503
    assert pool.rows()[0]["status"] == "pending"
    assert pool.rows()[0]["id"] == stored["id"]
    assert pool.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    pool.db.close()
