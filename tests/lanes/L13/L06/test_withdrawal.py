import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[4]


def test_cancellation_fixtures_bind_every_request_field(modules):
    contract = modules(
        "cancellation_contract", "packages/contracts-catalog/withdrawal/cancellation.py"
    )
    fixtures = json.loads(
        (
            ROOT / "packages/contracts-catalog/withdrawal/fixtures/cancellation.v1.json"
        ).read_text()
    )
    request = fixtures["request"]
    for name in ("success", "denied", "lost_response"):
        assert contract.matches_result(fixtures[name], request)
    assert not contract.matches_result(fixtures["stale"], request)
    for field in (
        "actor_id",
        "organization_id",
        "subject_id",
        "watch_id",
        "operation_id",
    ):
        wrong = fixtures["success"] | {field: str(uuid4())}
        assert not contract.matches_result(wrong, request)
    for value in (None, [], {}, fixtures["success"] | {"revision": True}):
        assert not contract.matches_result(value, request)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auction", "fixed_price"])
@pytest.mark.parametrize(
    "outcome",
    ["succeeded", "denied", "pending", "old_revision", "malformed", "invalid_status", "stale_revision", "stale_advanced", "denied_newer", "wrong_operation", "missing_binding", "wrong_actor", "wrong_organization", "wrong_revision"],
)
async def test_lost_response_retains_payload_and_never_restores_availability(
    modules, monkeypatch, mode, outcome
):
    newer = outcome == "denied_newer"
    if newer:
        outcome = "stale_revision"
    advanced = outcome == "stale_advanced"
    if advanced:
        outcome = "stale_revision"
    if mode == "auction" and outcome in {"wrong_operation", "missing_binding", "wrong_actor", "wrong_organization", "wrong_revision"}:
        pytest.skip("Orders receipt binding is checked on fixed-price withdrawals.")
    if mode == "fixed_price" and outcome == "stale_revision":
        pytest.skip("Stale cancellation receipts belong to the auction boundary.")
    route = modules(
        "withdrawal_routes", "services/catalog/modules/withdrawal/routes.py"
    )
    actor, listing, watch, operation = [uuid4() for _ in range(4)]
    row = dict(
        id=listing,
        revision=2,
        status="withdrawal_pending",
        facts={"sale_mode": mode},
        physical_watch_id=watch,
        owner_subject_id=actor,
        organization_id=None,
        is_demo=True,
    )
    intent = dict(
        id=operation,
        listing_id=listing,
        actor_id=actor,
        organization_id=None,
        base_revision=2,
        state="pending",
        operation_key="same",
        reason="Unavailable",
        remote_payload=None,
        created_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
        outcome=None,
    )
    person = SimpleNamespace(
        actor=SimpleNamespace(subject_id=actor, organization_id=None)
    )
    calls, events = [], []

    class Store:
        async def fetchrow(self, sql, *args):
            if "operation_key=$2" in sql and args[1] != intent["operation_key"]:
                return None
            if "SELECT listing_id" in sql:
                return {"listing_id": listing}
            if "INSERT INTO l13_listing_withdrawals" in sql:
                intent.update(id=args[0], operation_key=args[4], base_revision=args[5],
                              state="pending", remote_payload=None, outcome=None)
            if "UPDATE l13_listing_withdrawals SET outcome=" in sql:
                intent["outcome"] = json.loads(args[1])
            if "UPDATE l13_listing_withdrawals SET state" in sql:
                intent.update(state=args[1], outcome=json.loads(args[2]))
            return deepcopy(intent)

        async def execute(self, sql, *args):
            if "SET remote_payload" in sql:
                intent["remote_payload"] = json.loads(args[1])
            if "SET status='withdrawal_pending'" in sql:
                row["status"] = "withdrawal_pending"
            elif "UPDATE catalog_listings SET status" in sql:
                row.update(status=args[1], revision=args[2])

    store = Store()

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield store

    async def owned(*args):
        return person, row

    async def locked(*args):
        return row

    async def enqueue(*args):
        events.append(args)

    async def remote(request, dependency, method, path, **kwargs):
        if method == "GET":
            return dict(
                watch_id=str(watch),
                listing_id=str(listing),
                listing_revision=2,
                revision=1,
            )
        assert row["status"] == "withdrawal_pending"
        payload = kwargs["json"]
        assert payload == intent["remote_payload"]
        calls.append((dependency, path, deepcopy(payload)))
        if len(calls) == 1:
            raise route.PublicError("unavailable", "Unavailable", status=503)
        if outcome == "malformed":
            return {"status": "denied"}
        if outcome == "invalid_status":
            return {"status": []}
        if mode == "auction":
            fixtures = json.loads(
                (
                    ROOT
                    / "packages/contracts-catalog/withdrawal/fixtures/cancellation.v1.json"
                ).read_text()
            )
            template = fixtures[
                "lost_response"
                if outcome == "pending"
                else "denied"
                if outcome in {"denied", "stale_revision"}
                else "success"
            ]
            if advanced:
                row.update(status="published", revision=4)
            return (
                template
                | payload
                | dict(
                    state="succeeded" if outcome == "old_revision" else "denied" if outcome == "stale_revision" else outcome,
                    code="bid_exists" if newer else "stale_revision" if outcome == "stale_revision" else template["code"],
                    next_action="exception_route" if newer else "reload" if outcome == "stale_revision" else template["next_action"],
                    revision=1 if outcome == "old_revision" else 4 if outcome == "stale_revision" else 2 if outcome == "denied" else 3,
                )
            )
        binding = payload | {"actor_id": str(actor), "organization_id": None}
        if outcome == "wrong_operation":
            binding["source_id"] = str(uuid4())
        if outcome == "wrong_actor":
            binding["actor_id"] = str(uuid4())
        if outcome == "wrong_organization":
            binding["organization_id"] = str(uuid4())
        if outcome == "wrong_revision":
            binding["expected_revision"] += 1
        return dict(
            binding=None if outcome == "missing_binding" else binding,
            status="denied" if outcome in {"wrong_operation", "missing_binding", "wrong_actor", "wrong_organization", "wrong_revision"} else outcome,
            watch=dict(
                watch_id=str(watch),
                listing_id=str(listing),
                source_id=str(operation),
                listing_revision=2,
                status="withdrawn",
            ),
        )

    monkeypatch.setattr(route, "unit_of_work", transaction)
    monkeypatch.setattr(route, "owned", owned)
    monkeypatch.setattr(route, "source_locked", locked)
    monkeypatch.setattr(route, "assert_owner", lambda *args: None)
    monkeypatch.setattr(route, "service_request", remote)
    monkeypatch.setattr(route, "enqueue", enqueue)
    request = SimpleNamespace(
        headers={"Idempotency-Key": "same", "If-Match": "2"},
        app=SimpleNamespace(state=SimpleNamespace(pool=store, withdrawal_operator_id=actor)),
        state=SimpleNamespace(request_id=str(uuid4())),
    )
    body = route.Withdraw(reason="Unavailable")
    assert (await route.withdraw(listing, body, request))["status"] == "pending"
    assert row["status"] == "withdrawal_pending" and not events
    recovery = deepcopy(intent["outcome"]["recovery"])
    assert recovery == {
        "operator_id": str(actor),
        "next_action": "reconcile_same_operation",
        "first_response_due_at": "2026-11-17T00:00:00+00:00",
        "escalate_at": "2026-11-18T00:00:00+00:00",
        "escalation_action": "escalate_to_supervisor",
    }
    request.app.state.withdrawal_operator_id = uuid4()
    # Retry from retained request data; the remote response was lost.
    result = await route.withdraw(listing, body, request)
    assert result["status"] == (
        "pending"
        if outcome in {"pending", "old_revision", "malformed", "invalid_status", "wrong_operation", "missing_binding", "wrong_actor", "wrong_organization", "wrong_revision"}
        else "denied" if outcome == "stale_revision" else outcome
    )
    assert result["recovery"] == recovery
    assert route.view(deepcopy(intent))["recovery"] == recovery
    assert calls[0] == calls[1]
    assert calls[0][0] == ("auction" if mode == "auction" else "orders")
    if outcome in {"pending", "old_revision", "malformed", "invalid_status", "wrong_operation", "missing_binding", "wrong_actor", "wrong_organization", "wrong_revision"}:
        assert row["status"] == "withdrawal_pending" and not events
        if mode == "auction" and outcome == "pending":
            assert result["outcome"]["receipt"]["next_actor"] == "operator"
            assert result["outcome"]["receipt"]["next_review_at"]
            assert route.view(deepcopy(intent)) == result
        return
    if outcome == "stale_revision":
        assert row["status"] == ("published" if advanced else "withdrawal_pending")
        assert row["revision"] == (4 if advanced else 2)
        assert result["outcome"]["receipt"]["revision"] == 4
        assert result["next_action"] == "reload"
        assert result["outcome"]["exception_route"] is None
        assert not events
        assert await route.withdraw(listing, body, request) == result
        assert len(calls) == 2
        request.headers["Idempotency-Key"] = "fresh"
        request.headers["If-Match"] = "4"
        if not advanced:
            with pytest.raises(route.PublicError):
                await route.withdraw(listing, body, request)
        # Only current source reconciliation may supply availability and revision.
        row.update(status="published", revision=3)
        request.headers["If-Match"] = "3"
        with pytest.raises(route.PublicError):
            await route.withdraw(listing, body, request)
        row.update(status="published", revision=4)
        request.headers["If-Match"] = "4"
        fresh = await route.withdraw(listing, body, request)
        assert fresh["id"] != result["id"]
        assert fresh["base_revision"] == 4
        assert calls[-1][2]["expected_revision"] == 4
        assert calls[-1][2]["operation_id"] == fresh["id"]
        assert row["status"] == ("published" if advanced or newer else "withdrawal_pending")
        assert row["revision"] == 4
        assert not events
        return
    assert row["status"] == ("withdrawn" if outcome == "succeeded" else "published")
    if mode == "auction":
        assert result["outcome"]["receipt"]["revision"] == (2 if outcome == "denied" else 3)
        assert result["outcome"]["receipt"]["code"] == (
            "withdrawn" if outcome == "succeeded" else "bid_exists"
        )
        assert route.view(deepcopy(intent)) == result
    assert len(events) == int(outcome == "succeeded")
    assert (await route.withdraw(listing, body, request)) == result
    assert len(calls) == 2 and len(events) == int(outcome == "succeeded")


def test_reason_and_revision_bounds(modules):
    route = modules(
        "withdrawal_bounds", "services/catalog/modules/withdrawal/routes.py"
    )
    for reason in (" ", "x" * 201):
        with pytest.raises(ValueError):
            route.Withdraw(reason=reason)
    for revision in ("", "0", "-1", "1.5"):
        with pytest.raises(route.PublicError):
            route.command_headers(
                SimpleNamespace(
                    headers={"Idempotency-Key": "stable", "If-Match": revision}
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["actor", "organization", "missing", "none"])
async def test_operation_lookup_is_private(modules, monkeypatch, mismatch):
    route = modules(
        "withdrawal_lookup", "services/catalog/modules/withdrawal/routes.py"
    )
    actor, organization, listing, operation = [uuid4() for _ in range(4)]
    person = SimpleNamespace(
        actor=SimpleNamespace(subject_id=actor, organization_id=organization)
    )
    intent = dict(
        id=operation,
        listing_id=listing,
        actor_id=actor,
        organization_id=organization,
        base_revision=2,
        state="pending",
        operation_key="stable",
        reason="Unavailable",
        outcome=None,
    )
    if mismatch == "actor":
        intent["actor_id"] = uuid4()
    if mismatch == "organization":
        intent["organization_id"] = uuid4()

    async def principal(*args):
        return person

    async def fetchrow(*args):
        return None if mismatch == "missing" else intent

    checks = []

    async def owned(*args):
        checks.append(listing)
        return person, {}

    monkeypatch.setattr(route, "principal", principal)
    monkeypatch.setattr(route, "seller_scope", lambda *args: None)
    monkeypatch.setattr(route, "owned", owned)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(pool=SimpleNamespace(fetchrow=fetchrow))
        )
    )
    if mismatch == "none":
        assert (await route.lookup(operation, request))["operation_key"] == "stable"
        assert checks == [listing]
    else:
        with pytest.raises(route.PublicError):
            await route.lookup(operation, request)
        assert not checks


@pytest.mark.parametrize("state", ["success", "denied", "lost_response"])
@pytest.mark.parametrize("revision", [1, 2, 3, 4])
def test_result_revision_semantics(modules, state, revision):
    contract = modules(
        "revision_contract", "packages/contracts-catalog/withdrawal/cancellation.py"
    )
    fixtures = json.loads(
        (
            ROOT / "packages/contracts-catalog/withdrawal/fixtures/cancellation.v1.json"
        ).read_text()
    )
    result = fixtures[state] | {"revision": revision}
    assert contract.matches_result(result, fixtures["request"]) == (
        revision == 3 if state == "success" else revision >= 2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("contender", ["first_bid", "reservation", "callback"])
@pytest.mark.parametrize("winner", ["withdrawal", "contender"])
async def test_serialized_boundary_interleavings(modules, contender, winner):
    """Local contract model only; actual admission serialization remains unproven."""
    contract = modules(
        "race_contract", "packages/contracts-catalog/withdrawal/cancellation.py"
    )
    fixtures = json.loads(
        (
            ROOT / "packages/contracts-catalog/withdrawal/fixtures/cancellation.v1.json"
        ).read_text()
    )
    lock = asyncio.Lock()
    entered, release = asyncio.Event(), asyncio.Event()
    commitment, receipts, admitted = None, {}, []

    async def transition(kind, first=False):
        nonlocal commitment
        async with lock:
            if first:
                entered.set()
                await release.wait()
            if kind == "withdrawal":
                key = fixtures["request"]["operation_id"]
                if key not in receipts:
                    result = deepcopy(
                        fixtures["success" if commitment is None else "denied"]
                    )
                    if commitment is not None and contender != "first_bid":
                        result["code"] = "sale_commitment"
                        result["explanation"] = {
                            "en": "A sale commitment exists. Request an exception review.",
                            "ar": "يوجد التزام بيع. اطلب مراجعة الاستثناء.",
                        }
                    assert contract.matches_result(result, fixtures["request"])
                    receipts[key] = result
                    if commitment is None:
                        commitment = kind
                        admitted.append(kind)
                return deepcopy(receipts[key])
            if commitment is None:
                commitment = kind
                admitted.append(kind)
                return True
            return False

    first = "withdrawal" if winner == "withdrawal" else contender
    second = contender if winner == "withdrawal" else "withdrawal"

    async def race():
        first_task = asyncio.create_task(transition(first, True))
        await entered.wait()
        second_task = asyncio.create_task(transition(second))
        await asyncio.sleep(0)
        assert not second_task.done()
        release.set()
        return await asyncio.gather(first_task, second_task)

    results = await asyncio.wait_for(race(), timeout=1)
    receipt = results[0 if winner == "withdrawal" else 1]
    assert admitted == [first]
    assert receipt["state"] == ("succeeded" if winner == "withdrawal" else "denied")
    assert await transition("withdrawal") == receipt
    assert admitted == [first]


@pytest.mark.parametrize(
    "fixture,change",
    [
        ("success", {"code": "bid_exists"}),
        ("success", {"pending_reason": "reconciliation_required"}),
        ("denied", {"code": "withdrawn"}),
        ("denied", {"next_action": "none"}),
        ("denied", {"explanation": {"en": "A bid exists."}}),
        ("denied", {"explanation": {"en": " ", "ar": "توجد مزايدة"}}),
        ("lost_response", {"next_actor": "seller"}),
        ("lost_response", {"next_review_at": None}),
        ("lost_response", {"pending_reason": None}),
        ("lost_response", {"next_action": "none"}),
    ],
)
def test_inconsistent_recovery_does_not_settle(modules, fixture, change):
    contract = modules(
        "recovery_contract", "packages/contracts-catalog/withdrawal/cancellation.py"
    )
    fixtures = json.loads(
        (
            ROOT / "packages/contracts-catalog/withdrawal/fixtures/cancellation.v1.json"
        ).read_text()
    )
    assert not contract.matches_result(fixtures[fixture] | change, fixtures["request"])


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 1000])
async def test_history_pages_retain_older_pending_recovery(modules, monkeypatch, count):
    route = modules("withdrawal_pages", "services/catalog/modules/withdrawal/routes.py")
    actor = uuid4()
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=actor, organization_id=None))
    records = [dict(id=str(uuid4()), listing_id=str(uuid4()), base_revision=2,
                    state="pending", operation_key=f"original-{i}", reason="Unavailable",
                    outcome=None) for i in range(count)]
    calls = []

    async def principal(*args):
        return person

    async def fetchrow(sql, *args):
        calls.append(args)
        assert "w.actor_id=$1" in sql
        assert "w.organization_id IS NOT DISTINCT FROM $2::uuid" in sql
        assert "count(*) FROM scoped" in sql
        assert "ORDER BY created_at DESC,id DESC LIMIT $3 OFFSET $4" in sql
        return {"total": count, "items": json.dumps(records[args[3]:args[3]+args[2]])}

    monkeypatch.setattr(route, "principal", principal)
    monkeypatch.setattr(route, "seller_scope", lambda *args: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        pool=SimpleNamespace(fetchrow=fetchrow))))
    seen = []
    for page in range(1, max(1, (count + 24) // 25) + 1):
        result = await route.mine(request, page=page, page_size=25)
        assert result["total"] == count
        assert result["page"] == page and result["page_size"] == 25
        assert len(result["items"]) <= 25
        for item in result["items"]:
            assert item["next_action"] == "retry_same_operation"
            assert item["base_revision"] == 2
            seen.append(item["operation_key"])
    assert seen == [item["operation_key"] for item in records]
    assert all(args[:2] == (actor, None) for args in calls)


def test_migration_inventory_registers_every_additive_step():
    module = ROOT / "services/catalog/modules/withdrawal"
    inventory = json.loads((module / "module.json").read_text())["migrations"]
    assert inventory == [
        "migrations/L13_0001_withdrawal.sql",
        "migrations/L13_0002_withdrawal_attempts.sql",
    ]
    assert set(inventory) == {
        str(path.relative_to(module)) for path in (module / "migrations").glob("*.sql")
    }
    recovery = (module / inventory[1]).read_text()
    assert "DROP CONSTRAINT l13_listing_withdrawals_listing_id_key" in recovery
    assert "WHERE state='pending'" in recovery


@pytest.mark.asyncio
@pytest.mark.parametrize("operator", [None, "invalid"])
async def test_missing_responsible_operator_cannot_create_hold(modules, monkeypatch, operator):
    route = modules("withdrawal_assignment", "services/catalog/modules/withdrawal/routes.py")
    actor, listing = uuid4(), uuid4()
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=actor, organization_id=None))
    row = {"id": listing, "revision": 2, "status": "published"}
    writes = []

    class Store:
        async def fetchrow(self, *args):
            return None

        async def execute(self, sql, *args):
            if not sql.startswith("SELECT pg_advisory"):
                writes.append(sql)

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield Store()

    async def owned(*args):
        return person, row

    async def locked(*args):
        return row

    monkeypatch.setattr(route, "unit_of_work", transaction)
    monkeypatch.setattr(route, "owned", owned)
    monkeypatch.setattr(route, "source_locked", locked)
    monkeypatch.setattr(route, "assert_owner", lambda *args: None)
    request = SimpleNamespace(
        headers={"Idempotency-Key": "original", "If-Match": "2"},
        app=SimpleNamespace(state=SimpleNamespace(pool=Store(), withdrawal_operator_id=operator)),
    )
    with pytest.raises(route.PublicError):
        await route.withdraw(listing, route.Withdraw(reason="Unavailable"), request)
    assert not writes
    assert row["status"] == "published"
