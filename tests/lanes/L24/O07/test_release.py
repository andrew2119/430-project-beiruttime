from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from conftest import DATA, NOW, JournalFixture
from o07_releases.contracts import Command, Operation, Snapshot
from o07_releases.policy import conditions
from o07_releases.service import Denied, Releases


@pytest.mark.asyncio
async def test_net_once_and_durable_restart(service, journal, command, context):
    pending = await service.submit(command)
    assert pending.state == "pending"
    assert (pending.gross_minor, pending.fee_minor, pending.net_minor) == (500000, 25000, 475000)
    assert await service.submit(command) == pending
    journal.db.close()
    journal.db = JournalFixture(journal.path).db
    restarted = Releases(journal, clock=lambda: NOW)
    assert await restarted.lookup(context, command.operation_id) == pending
    paid = await restarted.recover(context, command.operation_id)
    assert paid.state == "paid_out" and paid.simulated
    assert await restarted.submit(command) == paid
    assert await restarted.recover(context, command.operation_id) == paid
    assert journal.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    assert journal.db.execute("SELECT count(*) FROM inbox").fetchone()[0] == 1


@pytest.mark.parametrize("field,value,reason", [
    ("payment_state", "pending", "payment_not_held"),
    ("payment_state", "unpaid", "payment_not_held"),
    ("payment_operation_id", None, "payment_not_held"),
    ("payment_revision", None, "payment_not_held"),
    ("held_principal_minor", 0, "principal_unavailable"),
    ("refund_reserved_minor", 1, "refund_active"),
    ("refunded_minor", 1, "refund_active"),
    ("accepted_economics", False, "economics_unaccepted"),
    ("accepted_fee_line", False, "economics_unaccepted"),
    ("dispute_window_hours", 71, "economics_unaccepted"),
    ("recipient_verified", False, "recipient_unverified"),
    ("recipient_owner_id", uuid4(), "recipient_unverified"),
    ("inspection_current", False, "inspection_required"),
    ("inspection_pass", False, "inspection_required"),
    ("inspection_independent", False, "inspection_required"),
    ("inspection_actual_custody", False, "inspection_required"),
    ("sources_current", False, "sources_unavailable"),
    ("hold_state", "held", "hold_active"),
    ("hold_state", "unknown", "hold_unknown"),
    ("receipt", None, "receipt_required"),
])
@pytest.mark.asyncio
async def test_missing_facts_never_reserve(service, journal, command, field, value, reason):
    journal.set_source(journal.source.model_copy(update={field: value}))
    result = await service.submit(command)
    assert result.state == "denied" and reason in result.missing
    assert journal.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0


@pytest.mark.parametrize("delta,open_window", [(-1, True), (0, False), (1, False)])
@pytest.mark.parametrize("hours", [72, 96, 168])
def test_full_window_boundary(journal, delta, open_window, hours):
    source = journal.source.model_copy(update={"dispute_window_hours": hours})
    now = source.receipt.received_at + timedelta(hours=hours, microseconds=delta)
    assert ("window_open" in conditions(source, now)) is open_window


@pytest.mark.parametrize("change", [
    {"kind": "dispatch"}, {"approved": False}, {"order_id": uuid4()}, {"watch_id": uuid4()},
    {"watch_revision": 3}, {"authorized_recipient": uuid4()}, {"recipient": uuid4()},
    {"received_at": NOW+timedelta(seconds=1)},
])
def test_receipt_must_be_actual_current_and_authorized(journal, change):
    source = journal.source
    source = source.model_copy(update={"receipt": source.receipt.model_copy(update=change)})
    assert "receipt_required" in conditions(source, NOW)


@pytest.mark.parametrize("kind", ["dealer_watch", "brand_watch", "service", "customization"])
@pytest.mark.asyncio
async def test_business_routes(service, journal, command, kind):
    job = kind in ("service", "customization")
    people = [uuid4(), uuid4(), uuid4()]
    source = journal.source.model_copy(update={
        "kind": kind, "inspection_pass": False, "inspection_current": False,
        "dispute_window_hours": 168, "assurance_current": not job,
        "buyer_fee_minor": 0 if job else 15000, "total_minor": 500000 if job else 515000,
        "quality_current": job, "quality_pass": job, "quality_actual_tests": job,
        "quality_fit_checked": job, "quality_returned_parts_checked": job,
        "assessor_id": people[0], "approver_id": people[1], "quality_reviewer_id": people[2],
    })
    journal.set_source(source)
    journal.now = source.receipt.received_at + timedelta(hours=168)
    result = await service.submit(command)
    assert result.state == "pending" and result.net_minor == 475000
    reason = "quality_required" if job else "assurance_required"
    changed = source.model_copy(update={"quality_pass": False, "assurance_current": False})
    assert reason in conditions(changed, journal.now)


@pytest.mark.parametrize("field", ["quality_current", "quality_pass", "quality_actual_tests",
                                    "quality_fit_checked", "quality_returned_parts_checked"])
def test_job_checks_and_independence(journal, field):
    a, b, c = uuid4(), uuid4(), uuid4()
    source = journal.source.model_copy(update={
        "kind": "service", "quality_current": True, "quality_pass": True, "quality_actual_tests": True,
        "quality_fit_checked": True, "quality_returned_parts_checked": True,
        "assessor_id": a, "approver_id": b, "quality_reviewer_id": c,
        "dispute_window_hours": 168, "buyer_fee_minor": 0, "total_minor": 500000,
    })
    now = NOW + timedelta(days=7)
    assert conditions(source, now) == ()
    assert "quality_required" in conditions(source.model_copy(update={field: False}), now)
    assert "quality_required" in conditions(source.model_copy(update={"quality_reviewer_id": a}), now)


@pytest.mark.asyncio
async def test_stale_scope_revocation_and_conflicting_duplicate(service, journal, command, context):
    stale = await service.submit(command.model_copy(update={"expected_revision": 6}))
    assert stale.missing == ("stale_revision",)
    with pytest.raises(Denied):
        await service.submit(command)
    other = command.model_copy(update={"operation_id": uuid4(), "organization_id": uuid4()})
    with pytest.raises(Denied):
        await service.submit(other)
    journal.allowed = False
    with pytest.raises(Denied):
        await service.current(context, command.subject_id)
    with pytest.raises(Denied):
        await service.lookup(context, command.operation_id)


@pytest.mark.parametrize("field", ["watch_id", "quote_id", "quote_revision", "policy_revision",
                                    "recipient_id", "recipient_revision"])
@pytest.mark.asyncio
async def test_bound_command(service, command, field):
    value = uuid4() if field.endswith("_id") else 99
    result = await service.submit(command.model_copy(update={field: value}))
    assert "binding_changed" in result.missing


@pytest.mark.asyncio
async def test_hold_race_rechecks_under_fence(service, journal, command, context):
    assert (await service.current(context, command.subject_id)).missing == ()
    journal.before_reserve = lambda: journal.set_source(journal.source.model_copy(update={"hold_state": "held"}))
    result = await service.submit(command)
    assert result.state == "denied" and "hold_active" in result.missing


@pytest.mark.asyncio
async def test_unknown_response_recovers_same_recipient(service, journal, command, context):
    journal.lose_response = True
    unknown = await service.submit(command)
    assert unknown.state == "pending" and unknown.pending_reason == "response_unknown"
    journal.set_source(journal.source.model_copy(update={"recipient_id": uuid4(), "recipient_revision": 4}))
    assert (await service.submit(command)).recipient_id == command.recipient_id
    redirected = command.model_copy(update={"recipient_id": journal.source.recipient_id, "recipient_revision": 4})
    with pytest.raises(Denied):
        await service.submit(redirected)
    second = redirected.model_copy(update={"operation_id": uuid4(), "expected_revision": journal.source.revision})
    assert "release_exists" in (await service.submit(second)).missing
    paid = await service.recover(context, command.operation_id)
    assert paid.recipient_id == command.recipient_id and paid.state == "paid_out"


@pytest.mark.asyncio
async def test_failed_transfer_stays_reserved(service, journal, command, context):
    await service.submit(command)
    journal.outcome = "declined"
    failed = await service.recover(context, command.operation_id)
    assert failed.state == "pending" and failed.pending_reason == "transfer_failed"
    assert journal.source.active_release_operation_id == command.operation_id
    assert journal.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1


@pytest.mark.parametrize("value", [-1, 0.5, float("inf"), True, 9_007_199_254_740_992])
def test_money_rejects_invalid(value):
    with pytest.raises(ValidationError):
        Snapshot.model_validate({**DATA["source"], "principal_minor": value})


def test_contract_fixtures():
    for name in ("success", "denied", "stale", "lost_response", "transfer_pending"):
        Operation.model_validate(DATA[name])
    with pytest.raises(ValidationError):
        Snapshot.model_validate({**DATA["source"], "currency": "EUR"})
    with pytest.raises(ValidationError):
        Snapshot.model_validate({**DATA["source"], "receipt": {**DATA["source"]["receipt"],
                                                             "received_at": "2026-11-01T12:00:00"}})
    with pytest.raises(ValidationError):
        Command.model_validate({**DATA["command"], "net_minor": 1})


@pytest.mark.asyncio
async def test_real_deadline_returns_unknown_without_new_reference(journal, command):
    import asyncio
    async def never_returns(*args):
        await asyncio.Event().wait()
    journal.reserve = never_returns
    service = Releases(journal, clock=lambda: NOW, timeout=0.01)
    result = await service.submit(command)
    assert result.operation_id == command.operation_id
    assert result.state == "pending" and result.pending_reason == "response_unknown"
    assert journal.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_retained_fee_is_never_recalculated(service, journal, command):
    journal.set_source(journal.source.model_copy(update={"business_fee_minor": 12345}))
    result = await service.submit(command)
    assert result.fee_minor == 12345 and result.net_minor == 487655


@pytest.mark.asyncio
async def test_cross_account_operation_reads_and_recovery(service, command, context):
    await service.submit(command)
    other = context.model_copy(update={"actor_id": uuid4()})
    with pytest.raises(Denied):
        await service.lookup(other, command.operation_id)
    with pytest.raises(Denied):
        await service.recover(other, command.operation_id)
    with pytest.raises(Denied):
        await service.lookup(context, uuid4())


@pytest.mark.asyncio
async def test_producer_binding_mismatch_is_unavailable(service, journal, command, context):
    async def foreign_current(*args):
        return journal.source.model_copy(update={"subject_id": uuid4()})
    journal.current = foreign_current
    with pytest.raises(ConnectionError):
        await service.current(context, command.subject_id)
    paid = Operation.model_validate(DATA["success"]).model_copy(update={"actor_id": uuid4()})
    async def foreign_result(*args):
        return paid
    journal.lookup = foreign_result
    journal.reconcile = foreign_result
    with pytest.raises(ConnectionError):
        await service.lookup(context, command.operation_id)
    with pytest.raises(ConnectionError):
        await service.recover(context, command.operation_id)


def test_contract_import_from_packaged_layout(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    from conftest import ROOT
    package = tmp_path / "domains/bt_contracts/orders/releases"
    package.mkdir(parents=True)
    shutil.copyfile(ROOT / "packages/contracts-orders/releases/v1.py", package / "v1.py")
    module = tmp_path / "app/modules/releases"
    module.mkdir(parents=True)
    for name in ("__init__.py", "contracts.py", "policy.py", "service.py", "routes.py"):
        shutil.copyfile(ROOT / "services/orders/modules/releases" / name, module / name)
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "domains")+os.pathsep+str(tmp_path / "app")}
    result = subprocess.run([sys.executable, "-c", "from modules.releases.routes import router_for"],
                            env=env, cwd=tmp_path, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize("hold", ["held", "unknown"])
@pytest.mark.asyncio
async def test_post_reservation_hold_records_pending_investigation(service, journal, command, context, hold):
    await service.submit(command)
    journal.set_source(journal.source.model_copy(update={"hold_state": hold, "hold_revision": 2}))
    result = await service.recover(context, command.operation_id)
    assert result.state == "pending" and result.next_action == "reconcile_transfer"
    assert (await service.lookup(context, command.operation_id)) == result
    assert journal.db.execute("SELECT count(*) FROM inbox").fetchone()[0] == 0
    assert journal.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
