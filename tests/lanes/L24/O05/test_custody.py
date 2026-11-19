import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from services.orders.modules.custody.adapter import Adapter
from services.orders.modules.custody.domain import ACTIONS, Context, CustodyError, Facts, proof_digest, window_open
from services.orders.modules.custody.repository import Custody


NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
CONTEXT = Context("buyer", None)


class Provider:
    def __init__(self, facts):
        self.facts = facts
        self.allowed = True
        self.unavailable = False

    @contextmanager
    def current(self, context, order_id, timeout_seconds):
        assert timeout_seconds == 2
        if self.unavailable:
            raise TimeoutError
        staff = context.actor_id == "staff" and context.organization_id == self.facts.job_organization_id
        if not self.allowed or not (staff or context == CONTEXT):
            raise CustodyError("denied")
        if order_id != self.facts.order_id:
            raise CustodyError("denied")
        yield self.facts


@pytest.fixture
def custody(tmp_path):
    provider = Provider(Facts(
        order_id="order", watch_id="watch", watch_revision=1, source_revision=1,
        quote_id="quote", quote_revision=1, policy_revision=1, route="dealer",
        buyer_id="buyer", seller_id="seller", custodian="seller", recipients=("buyer", "delegate"),
        accessories=("box", "papers"), condition="agreed", address="agreed-address",
        operator_id="operator", permitted_actions=tuple(ACTIONS), paid_held=True,
        business_assurance_current=True, principal_minor=500000, seller_commission_minor=25000,
        assignment_revision=1, inspection_revision=1, quality_revision=1,
        quality_reviewer_id="quality", assessor_id="assessor", approver_id="approver",
        paid_held_at=NOW.isoformat(),
        collection_operation_id="collection", collection_revision=1,
    ))
    return Custody(tmp_path / "custody.sqlite", provider, lambda: NOW)


def command(action="prepare", revision=0, operation="operation", **extra):
    return dict(schema_version="custody.v1", operation_id=operation, subject_id="order", watch_id="watch",
                actor_id="buyer", organization_id=None, expected_revision=revision, source_revision=1,
                quote_id="quote", quote_revision=1, policy_revision=1, watch_revision=1, action=action, **extra)


def proof(**extra):
    return dict(watch_id="watch", recipient="buyer", condition="agreed", accessories=["box", "papers"],
                location="delivery", address="agreed-address", received_at=NOW.isoformat(),
                signed_handoff=True, source="buyer_acknowledgement", **extra)


def assert_error(code, callback):
    with pytest.raises(CustodyError) as error:
        callback()
    assert error.value.code == code


def test_dispatch_never_receives(custody):
    custody.execute(CONTEXT, command())
    result = custody.execute(CONTEXT, command("dispatch", 1, "dispatch"))
    assert result["state"] == "in_transit"
    assert result["custodian"] == "seller"
    assert result["buyer_received_at"] is None
    assert result["dispute_deadline"] is None


@pytest.mark.parametrize("route,hours", [("private", 72), ("dealer", 168), ("brand", 168), ("job", 168)])
def test_actual_receipt_windows(custody, route, hours):
    custody.provider.facts = replace(custody.provider.facts, route=route, quality_current_pass=True)
    revision = 0
    if route == "job":
        job_intake(custody)
        revision = 1
    if route == "private":
        expert_receipt(custody)
        custody.provider.facts = replace(custody.provider.facts, inspection="passed", inspection_current=True,
                                         expert_receipt_id="expert")
        revision = 1
    state = custody.execute(CONTEXT, command("buyer_receipt", revision, "receipt", proof=proof()))
    assert state["window_hours"] == hours
    deadline = NOW + timedelta(hours=hours)
    assert state["dispute_deadline"] == deadline.isoformat()
    assert window_open(state, deadline - timedelta(microseconds=1))
    assert not window_open(state, deadline)
    assert not window_open(state, deadline + timedelta(microseconds=1))


def expert_receipt(custody):
    custody.provider.facts = replace(custody.provider.facts, route="private", expert_id="buyer",
                                     expert_independent=True, approved_proof_operation="expert")
    value = proof()
    value["source"] = "approved_proof"
    custody.provider.facts = replace(custody.provider.facts, approved_proof_digest=proof_digest(value))
    return custody.execute(CONTEXT, command("expert_receipt", operation="expert", proof=value))


def job_intake(custody):
    value = {**proof(), "recipient": "business-intake", "source": "approved_proof"}
    custody.provider.facts = replace(custody.provider.facts, route="job", job_organization_id="business",
                                     intake_recipient="business-intake", job_intake_receipt_id="intake",
                                     approved_proof_operation="intake", approved_proof_digest=proof_digest(value))
    body = command("job_intake", operation="intake", proof=value)
    body.update(actor_id="staff", organization_id="business")
    return custody.execute(Context("staff", "business"), body)


@pytest.mark.parametrize("result,current", [("missing", False), ("failed", True),
                                            ("inconclusive", True), ("passed", False)])
def test_private_waits_for_current_result(custody, result, current):
    expert_receipt(custody)
    custody.provider.facts = replace(custody.provider.facts, inspection=result, inspection_current=current,
                                     expert_receipt_id="expert")
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", 1, proof=proof())))
    assert custody.read(CONTEXT, "order")["buyer_received_at"] is None


def test_pass_without_actual_expert_receipt_denied(custody):
    custody.provider.facts = replace(custody.provider.facts, route="private", inspection="passed",
                                     inspection_current=True, expert_independent=True, expert_receipt_id="fiction")
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", proof=proof())))


@pytest.mark.parametrize("change,reason", [({"watch_id": "other"}, "wrong_watch"),
                                          ({"recipient": "stranger"}, "wrong_recipient"),
                                          ({"accessories": ["box"]}, "missing_accessories"),
                                          ({"condition": "damaged"}, "condition")])
def test_receipt_mismatch_holds(custody, change, reason):
    value = {**proof(), **change}
    result = custody.execute(CONTEXT, command("buyer_receipt", proof=value))
    assert result["held"] and result["pending_reason"] == reason
    assert result["custodian"] == "seller" and result["buyer_received_at"] is None
    assert result["next_actor"] == "operator"
    assert result["next_review_at"] == (NOW + timedelta(hours=24)).isoformat()
    assert_error("held", lambda: custody.execute(CONTEXT, command("prepare", 1, "next")))


@pytest.mark.parametrize("reason", ["loss", "damage", "non_shipment"])
def test_incident_holds(custody, reason):
    result = custody.execute(CONTEXT, command("incident", reason=reason))
    assert result["state"] == "investigation" and result["held"]
    assert result["custodian"] == "seller"


def test_missed_pickup_remains_ready(custody):
    custody.execute(CONTEXT, command())
    custody.execute(CONTEXT, command("ready", 1, "ready"))
    result = custody.execute(CONTEXT, command("miss_pickup", 2, "missed"))
    assert result["state"] == "ready_for_pickup" and result["held"]
    assert not result["buyer_received_at"]


@pytest.mark.parametrize("confirmed,instruction", [(False, False), (False, True), (True, False)])
def test_failed_charge_unknown_blocks_return(custody, confirmed, instruction):
    expert_receipt(custody)
    custody.provider.facts = replace(custody.provider.facts, inspection="failed", inspection_current=True,
                                     expert_receipt_id="expert", collection_confirmed=confirmed,
                                     return_instruction=instruction, approved_proof_operation="return")
    value = {**proof(), "recipient": "seller", "source": "approved_proof"}
    custody.provider.facts = replace(custody.provider.facts, approved_proof_digest=proof_digest(value))
    result = custody.execute(CONTEXT, command("return_receipt", 1, "return", proof=value))
    assert result["state"] == "return_held" and result["held"]
    assert result["restrict_new_private_publication"]
    assert result["next_actor"] == "operator"
    assert result["buyer_received_at"] is None


def test_confirmed_failed_return(custody):
    expert_receipt(custody)
    custody.provider.facts = replace(custody.provider.facts, inspection="failed", inspection_current=True,
                                     expert_receipt_id="expert", collection_confirmed=True,
                                     return_instruction=True, approved_proof_operation="return")
    value = {**proof(), "recipient": "seller", "source": "approved_proof"}
    custody.provider.facts = replace(custody.provider.facts, approved_proof_digest=proof_digest(value))
    result = custody.execute(CONTEXT, command("return_receipt", 1, "return", proof=value))
    assert result["state"] == "returned" and result["buyer_received_at"] is None


def test_job_final_handover_needs_current_quality(custody):
    job_intake(custody)
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", 1, proof=proof())))


def test_business_needs_assurance_without_inspection(custody):
    custody.provider.facts = replace(custody.provider.facts, business_assurance_current=False,
                                     inspection="passed", inspection_current=True)
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", proof=proof())))


def test_lost_response_restart_and_conflicting_retry(custody):
    result = custody.execute(CONTEXT, command())
    restarted = Custody(custody.database, custody.provider, lambda: NOW)
    assert restarted.execute(CONTEXT, command()) == result
    assert restarted.lookup(CONTEXT, "order", "operation") == result
    assert_error("conflict", lambda: restarted.execute(CONTEXT, command("dispatch")))
    with restarted.connect() as db:
        assert db.execute("SELECT count(*) FROM l24_custody_outbox").fetchone()[0] == 1


def test_current_permission_on_read_and_duplicate(custody):
    custody.execute(CONTEXT, command())
    custody.provider.allowed = False
    for callback in [lambda: custody.read(CONTEXT, "order"), lambda: custody.execute(CONTEXT, command()),
                     lambda: custody.lookup(CONTEXT, "order", "operation")]:
        assert_error("denied", callback)


@pytest.mark.parametrize("field", ["watch_revision", "source_revision", "quote_revision", "policy_revision"])
def test_stale_sources(custody, field):
    value = command()
    value[field] = 2
    assert_error("stale", lambda: custody.execute(CONTEXT, value))
    assert custody.read(CONTEXT, "order") is None


def test_current_record_revision(custody):
    custody.execute(CONTEXT, command())
    assert_error("stale", lambda: custody.execute(CONTEXT, command("dispatch", 0, "new")))


def test_retained_quote_cannot_be_replaced(custody):
    custody.execute(CONTEXT, command())
    custody.provider.facts = replace(custody.provider.facts, quote_revision=2)
    body = command("dispatch", 1, "new")
    body["quote_revision"] = 2
    assert_error("stale", lambda: custody.execute(CONTEXT, body))


def test_timeout_and_same_retry(custody):
    custody.provider.unavailable = True
    assert Adapter(custody).call("command", CONTEXT, command=command()) == (
        503, {"schema_version": "custody.v1", "state": "unavailable", "retry_same_operation": True})
    custody.provider.unavailable = False
    assert custody.execute(CONTEXT, command())["revision"] == 1


def test_outbox_excludes_private_proof(custody):
    custody.execute(CONTEXT, command("buyer_receipt", proof=proof()))
    with custody.connect() as db:
        event = json.loads(db.execute("SELECT event FROM l24_custody_outbox").fetchone()[0])
    assert set(event) == {"schema_version", "operation_id", "subject_id", "revision"}


@pytest.mark.parametrize("change", [{"received_at": "2026-11-17T13:00:00+00:00"},
                                    {"received_at": "2026-11-17T12:00:00"},
                                    {"signed_handoff": False}, {"source": "dispatch_scan"},
                                    {"address": "changed-address"}])
def test_invalid_or_unapproved_proof(custody, change):
    status, result = Adapter(custody).call("command", CONTEXT,
                                         command=command("buyer_receipt", proof={**proof(), **change}))
    assert status in {403, 422}
    assert result["state"] in {"invalid", "denied"}
    assert custody.read(CONTEXT, "order") is None


def test_cross_account_and_organization(custody):
    assert_error("denied", lambda: custody.execute(Context("other", None), command()))
    assert_error("denied", lambda: custody.execute(Context("buyer", "other"), command()))
    assert_error("denied", lambda: custody.read(CONTEXT, "other-order"))


@pytest.mark.parametrize("amount", [1.5, True, -1, 2**53])
def test_finite_integer_money(custody, amount):
    custody.provider.facts = replace(custody.provider.facts, principal_minor=amount)
    assert_error("unavailable", lambda: custody.execute(CONTEXT, command()))


def test_atomic_rollback(custody):
    with custody.connect() as db:
        db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON l24_custody_outbox "
                   "BEGIN SELECT RAISE(ABORT, 'rejected'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        custody.execute(CONTEXT, command())
    assert custody.read(CONTEXT, "order") is None
    with custody.connect() as db:
        assert db.execute("SELECT count(*) FROM l24_custody_operations").fetchone()[0] == 0


def test_no_seeded_acceptance_in_fixtures():
    from pathlib import Path
    fixtures = json.loads(Path("packages/contracts-orders/custody/fixtures/cases.json").read_text())
    assert fixtures["synthetic"] is True
    assert {row["name"] for row in fixtures["cases"]} == {"success", "denied", "stale", "lost_response", "timeout"}


def test_approved_proof_cannot_be_replaced(custody):
    value = {**proof(), "source": "approved_proof"}
    custody.provider.facts = replace(custody.provider.facts, approved_proof_operation="operation",
                                     approved_proof_digest=proof_digest(value))
    value["location"] = "substituted"
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", proof=value)))


def test_reassignment_invalidates_old_expert_handover(custody):
    expert_receipt(custody)
    custody.provider.facts = replace(custody.provider.facts, inspection="passed", inspection_current=True,
                                     expert_receipt_id="expert", assignment_revision=2)
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", 1, proof=proof())))


def test_job_quality_independence(custody):
    job_intake(custody)
    custody.provider.facts = replace(custody.provider.facts, route="job", quality_current_pass=True,
                                     quality_reviewer_id="assessor")
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", 1, proof=proof())))


def test_history_true_total_and_pagination(custody):
    assert custody.history(CONTEXT, "order")["total"] == 0
    custody.execute(CONTEXT, command())
    for index in range(1, 1000):
        current = custody.read(CONTEXT, "order")
        custody.provider.facts = replace(custody.provider.facts,
                                         incident_resolved_revision=current["incident_revision"])
        custody.execute(CONTEXT, command("incident", index, f"incident-{index}", reason="damage"))
    first = custody.history(CONTEXT, "order")
    assert first["total"] == 1000 and len(first["items"]) == 25
    assert first["items"][0]["revision"] == 1000
    last = custody.history(CONTEXT, "order", 975)
    assert last["total"] == 1000 and last["items"][-1]["revision"] == 1
    assert "proof" not in first["items"][0]
    assert_error("invalid", lambda: custody.history(CONTEXT, "order", limit=101))
    custody.provider.allowed = False
    assert_error("denied", lambda: custody.history(CONTEXT, "order"))


def test_job_intake_is_scoped_and_does_not_complete(custody):
    state = job_intake(custody)
    assert state["state"] == "job_received" and state["custodian"] == "business-intake"
    assert state["buyer_received_at"] is None and state["dispute_deadline"] is None
    assert state["job_intake_receipt_id"] == "intake"
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", 1, proof=proof())))


def test_quality_without_intake_denied(custody):
    custody.provider.facts = replace(custody.provider.facts, route="job", quality_current_pass=True)
    assert_error("denied", lambda: custody.execute(CONTEXT, command("buyer_receipt", proof=proof())))


def test_wrong_business_intake_denied(custody):
    job_intake(custody)
    body = command("job_intake", 1, "another", proof=proof())
    body.update(actor_id="staff", organization_id="other")
    assert_error("denied", lambda: custody.execute(Context("staff", "other"), body))


@pytest.mark.parametrize("action,field,hours,code", [
    ("prepare", "dispatch_due_at", 72, "dispatch_review"),
    ("ready", "pickup_reminder_at", 48, "pickup_reminder"),
    ("ready", "pickup_due_at", 168, "pickup_review"),
    ("incident", "next_review_at", 24, "support_response"),
    ("incident", "escalation_at", 48, "support_escalation"),
])
def test_operational_before_equal_after(custody, action, field, hours, code):
    from services.orders.modules.custody.domain import due_actions
    if action == "ready":
        custody.execute(CONTEXT, command())
        state = custody.execute(CONTEXT, command("ready", 1, "ready"))
    elif action == "incident":
        state = custody.execute(CONTEXT, command("incident", reason="damage"))
    else:
        state = custody.execute(CONTEXT, command())
    boundary = NOW + timedelta(hours=hours)
    assert state[field] == boundary.isoformat()
    for delta, expected in [(-1, False), (0, True), (1, True)]:
        due = due_actions(state, custody.provider.facts, boundary + timedelta(microseconds=delta))
        assert (code in {item["code"] for item in due}) is expected
    if action == "ready":
        assert state["state"] == "ready_for_pickup" and state["buyer_received_at"] is None
    if action == "incident":
        assert state["insurance_review"] == {"simulated": True, "declared_value_minor": 500000,
                                              "state": "review_required", "actual_cover_claimed": False}


def test_expert_deadline_counts_beirut_weekdays(custody):
    from services.orders.modules.custody.domain import due_actions, expert_deadline
    friday = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    assert expert_deadline(friday) == datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    state = expert_receipt(custody)
    boundary = NOW + timedelta(days=2)
    assert state["expert_decision_due_at"] == boundary.isoformat()
    for delta, expected in [(-1, False), (0, True), (1, True)]:
        due = due_actions(state, custody.provider.facts, boundary + timedelta(microseconds=delta))
        assert ("expert_decision_review" in {item["code"] for item in due}) is expected

@pytest.mark.parametrize("completed", [False, True])
def test_authorized_incident_resolution_preserves_receipt(custody, completed):
    initial = custody.execute(CONTEXT, command("buyer_receipt", proof=proof()) if completed else command())
    held = custody.execute(CONTEXT, command("incident", 1, "damage", reason="damage"))
    resolve = command("resolve_incident", 2, "resolve")
    assert_error("denied", lambda: custody.execute(CONTEXT, resolve))
    custody.provider.facts = replace(custody.provider.facts, incident_resolved_revision=0)
    assert_error("denied", lambda: custody.execute(CONTEXT, resolve))
    custody.provider.facts = replace(custody.provider.facts, incident_resolved_revision=held["incident_revision"],
                                     permitted_actions=tuple(ACTIONS - {"resolve_incident"}))
    assert_error("denied", lambda: custody.execute(CONTEXT, resolve))
    custody.provider.facts = replace(custody.provider.facts, permitted_actions=tuple(ACTIONS))
    result = custody.execute(CONTEXT, resolve)
    assert not result["held"] and result["state"] == initial["state"]
    for key in ("buyer_received_at", "dispute_deadline", "window_hours", "custodian", "incident_revision"):
        assert result[key] == held[key]
    assert result["pending_reason"] is None and result["next_actor"] is None
    assert result["next_review_at"] is None and result["escalation_at"] is None
    restarted = Custody(custody.database, custody.provider, lambda: NOW)
    assert restarted.execute(CONTEXT, resolve) == result
    assert restarted.read(CONTEXT, "order")["held"] is False
    assert restarted.history(CONTEXT, "order")["total"] == 3
    assert_error("denied", lambda: restarted.execute(CONTEXT, command("resolve_incident", 3, "again")))

def test_new_incident_restores_latest_lifecycle_after_implicit_recovery(custody):
    custody.execute(CONTEXT, command())
    custody.execute(CONTEXT, command("incident", 1, "first", reason="damage"))
    custody.provider.facts = replace(custody.provider.facts, incident_resolved_revision=1)
    receipt = custody.execute(CONTEXT, command("buyer_receipt", 2, "receipt", proof=proof()))
    custody.execute(CONTEXT, command("incident", 3, "second", reason="damage"))
    custody.provider.facts = replace(custody.provider.facts, incident_resolved_revision=2)
    resolved = custody.execute(CONTEXT, command("resolve_incident", 4, "resolve"))
    assert resolved["state"] == "received" and not resolved["held"]
    assert resolved["buyer_received_at"] == receipt["buyer_received_at"]
    assert resolved["dispute_deadline"] == receipt["dispute_deadline"]

def test_successive_incidents_keep_received_lifecycle(custody):
    receipt = custody.execute(CONTEXT, command("buyer_receipt", proof=proof()))
    custody.execute(CONTEXT, command("incident", 1, "first", reason="damage"))
    custody.provider.facts = replace(custody.provider.facts, incident_resolved_revision=1)
    custody.execute(CONTEXT, command("incident", 2, "second", reason="loss"))
    custody.provider.facts = replace(custody.provider.facts, incident_resolved_revision=2)
    resolved = custody.execute(CONTEXT, command("resolve_incident", 3, "resolve"))
    assert resolved["state"] == "received" and not resolved["held"]
    assert resolved["dispute_deadline"] == receipt["dispute_deadline"]
