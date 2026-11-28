"""Current-source custody decisions. No money movement is performed here."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Literal
from zoneinfo import ZoneInfo


class CustodyError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() != timedelta(0):
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise CustodyError("invalid") from None


@dataclass(frozen=True)
class Context:
    actor_id: str
    organization_id: str | None


@dataclass(frozen=True)
class Facts:
    order_id: str
    watch_id: str
    watch_revision: int
    source_revision: int
    quote_id: str
    quote_revision: int
    policy_revision: int
    route: Literal["private", "dealer", "brand", "job"]
    buyer_id: str
    seller_id: str
    custodian: str
    recipients: tuple[str, ...]
    accessories: tuple[str, ...]
    condition: str
    address: str
    operator_id: str
    paid_held: bool = False
    permitted_actions: tuple[str, ...] = ()
    inspection: str = "missing"
    inspection_current: bool = False
    expert_id: str | None = None
    expert_independent: bool = False
    expert_receipt_id: str | None = None
    business_assurance_current: bool = False
    quality_current_pass: bool = False
    collection_confirmed: bool = False
    collection_operation_id: str | None = None
    collection_revision: int | None = None
    return_instruction: bool = False
    approved_proof_operation: str | None = None
    approved_proof_digest: str | None = None
    inspection_revision: int | None = None
    assignment_revision: int | None = None
    quality_revision: int | None = None
    quality_reviewer_id: str | None = None
    assessor_id: str | None = None
    approver_id: str | None = None
    job_organization_id: str | None = None
    intake_recipient: str | None = None
    job_intake_receipt_id: str | None = None
    paid_held_at: str | None = None
    incident_resolved_revision: int | None = None
    currency: str = "USD"
    principal_minor: int = 0
    seller_commission_minor: int = 0
    return_trip_minor: int = 0


ACTIONS = frozenset({"prepare", "dispatch", "ready", "expert_receipt", "job_intake", "buyer_receipt",
                     "return_receipt", "incident", "miss_pickup", "resolve_incident"})
INCIDENTS = frozenset({"wrong_watch", "wrong_recipient", "missing_accessories", "condition",
                       "loss", "damage", "non_shipment", "missed_pickup", "collection_pending",
                       "return_instruction_pending"})
BINDINGS = ("watch_id", "watch_revision", "source_revision", "quote_id", "quote_revision", "policy_revision")


def proof_digest(proof: dict) -> str:
    return hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def current_private_pass(facts: Facts, state: dict) -> bool:
    return bool(facts.inspection == "passed" and facts.inspection_current and facts.expert_independent
                and facts.expert_id and facts.expert_id != facts.seller_id
                and facts.inspection_revision is not None and facts.assignment_revision is not None
                and state["expert_receipt_id"] and facts.expert_receipt_id == state["expert_receipt_id"]
                and state.get("expert_custodian") == facts.expert_id
                and state.get("expert_watch_revision") == facts.watch_revision
                and state.get("expert_assignment_revision") == facts.assignment_revision)


def expert_deadline(received: datetime) -> datetime:
    civil = received.astimezone(ZoneInfo("Asia/Beirut"))
    remaining = 2
    while remaining:
        civil += timedelta(days=1)
        if civil.weekday() < 5:
            remaining -= 1
    return civil.astimezone(timezone.utc)


def due_actions(state: dict, facts: Facts, now: datetime) -> list[dict]:
    due = []

    def add(code, value):
        if value and now >= instant(value):
            due.append({"code": code, "due_at": value, "next_actor": facts.operator_id})

    if not state.get("dispatched_at") and not state.get("buyer_received_at"):
        add("dispatch_review", state.get("dispatch_due_at"))
    if state.get("expert_receipt_id") and not facts.inspection_current:
        add("expert_decision_review", state.get("expert_decision_due_at"))
    if state["state"] == "ready_for_pickup":
        add("pickup_reminder", state.get("pickup_reminder_at"))
        add("pickup_review", state.get("pickup_due_at"))
    if state["held"]:
        add("support_response", state.get("next_review_at"))
        add("support_escalation", state.get("escalation_at"))
    return due


def validate(command: dict, context: Context) -> None:
    required = {"schema_version", "operation_id", "subject_id", "watch_id", "actor_id",
                "organization_id", "expected_revision", "source_revision", "quote_id",
                "quote_revision", "policy_revision", "watch_revision", "action"}
    if not isinstance(command, dict) or not required <= command.keys():
        raise CustodyError("invalid")
    if command.keys() - required - {"proof", "reason"}:
        raise CustodyError("invalid")
    for key in ("operation_id", "subject_id", "watch_id", "actor_id", "quote_id"):
        value = command[key]
        if not isinstance(value, str) or not 1 <= len(value) <= 100 or not all(
            c.isascii() and (c.isalnum() or c in "-_") for c in value
        ):
            raise CustodyError("invalid")
    organization = command["organization_id"]
    if organization is not None and (not isinstance(organization, str) or not 1 <= len(organization) <= 100 or not all(
        c.isascii() and (c.isalnum() or c in "-_") for c in organization
    )):
        raise CustodyError("invalid")
    for key in ("expected_revision", "source_revision", "quote_revision", "policy_revision", "watch_revision"):
        if type(command[key]) is not int or not 0 <= command[key] <= 2**53 - 1:
            raise CustodyError("invalid")
    if command["schema_version"] != "custody.v1" or not isinstance(command["action"], str):
        raise CustodyError("invalid")
    if command["action"] not in ACTIONS:
        raise CustodyError("invalid")
    if (command["actor_id"], command["organization_id"]) != (context.actor_id, context.organization_id):
        raise CustodyError("denied")


def check_facts(command: dict, facts: Facts) -> None:
    if facts.route not in {"private", "dealer", "brand", "job"} or facts.order_id != command["subject_id"]:
        raise CustodyError("unavailable")
    if any(command[key] != getattr(facts, key) for key in BINDINGS):
        raise CustodyError("stale")
    if command["action"] not in facts.permitted_actions:
        raise CustodyError("denied")
    amounts = (facts.principal_minor, facts.seller_commission_minor, facts.return_trip_minor)
    if facts.currency != "USD" or any(type(n) is not int or not 0 <= n <= 2**53 - 1 for n in amounts):
        raise CustodyError("unavailable")
    if not facts.paid_held:
        raise CustodyError("pending")


def transition(command: dict, facts: Facts, previous: dict | None, now: datetime) -> dict:
    action = command["action"]
    revision = previous["revision"] if previous else 0
    if command["expected_revision"] != revision:
        raise CustodyError("stale")
    state = dict(previous) if previous else {
        "state": "awaiting_prerequisites", "revision": 0, "custodian": facts.custodian,
        "buyer_received_at": None, "dispute_deadline": None, "window_hours": None,
        "incident_revision": 0, "held": False, "expert_receipt_id": None,
        "route": facts.route,
        "job_intake_receipt_id": None,
    }
    if not previous:
        if facts.paid_held_at is None:
            raise CustodyError("unavailable")
        paid = instant(facts.paid_held_at)
        if paid > now:
            raise CustodyError("unavailable")
        state["dispatch_due_at"] = (paid + timedelta(days=3)).isoformat()
    if state["route"] != facts.route or (previous and any(
        previous[key] != getattr(facts, key) for key in ("watch_id", "quote_id", "quote_revision", "policy_revision")
    )):
        raise CustodyError("stale")
    if action == "resolve_incident":
        if not state["held"] or facts.incident_resolved_revision != state["incident_revision"]:
            raise CustodyError("denied")
        state.update(held=False, state=state.pop("pre_incident_state",
                     "received" if state["buyer_received_at"] else "returned" if state["state"] == "returned" else "awaiting_prerequisites"),
                     revision=revision + 1, pending_reason=None, next_actor=None, next_review_at=None,
                     escalation_at=None, resolved_incident_revision=state["incident_revision"])
        return state
    if state["held"]:
        if facts.incident_resolved_revision != state["incident_revision"]:
            raise CustodyError("held")
        state["held"] = False
        if action != "incident":
            state.pop("pre_incident_state", None)
    if state["buyer_received_at"] or state["state"] == "returned":
        if action != "incident":
            raise CustodyError("denied")
    state.update(revision=revision + 1, pending_reason=None, next_actor=None, next_review_at=None)

    def hold(reason: str) -> dict:
        if not isinstance(reason, str) or reason not in INCIDENTS or not facts.operator_id:
            raise CustodyError("invalid")
        state.setdefault("pre_incident_state", state["state"])
        state.update(held=True, pending_reason=reason, next_actor=facts.operator_id,
                     next_review_at=(now + timedelta(hours=24)).isoformat(),
                     escalation_at=(now + timedelta(hours=48)).isoformat(),
                     incident_revision=state["incident_revision"] + 1)
        if reason in {"loss", "damage"}:
            state["insurance_review"] = {"simulated": True, "declared_value_minor": facts.principal_minor,
                                         "state": "review_required", "actual_cover_claimed": False}
        if reason != "missed_pickup":
            state["state"] = "investigation"
        if reason in {"collection_pending", "return_instruction_pending"}:
            state["state"] = "return_held"
            state["restrict_new_private_publication"] = True
        return state

    if action == "incident":
        return hold(command.get("reason"))
    if action == "miss_pickup":
        if state["state"] != "ready_for_pickup":
            raise CustodyError("denied")
        return hold("missed_pickup")
    if action in {"prepare", "dispatch", "ready"}:
        allowed = {
            "prepare": {"awaiting_prerequisites"},
            "dispatch": {"prepared", "expert_received", "job_received"},
            "ready": {"prepared", "in_transit", "expert_received", "job_received"},
        }
        if state["state"] not in allowed[action]:
            raise CustodyError("denied")
        if state["state"] == "expert_received" and not current_private_pass(facts, state):
            raise CustodyError("denied")
        state["state"] = {"prepare": "prepared", "dispatch": "in_transit", "ready": "ready_for_pickup"}[action]
        if action == "dispatch":
            state["dispatched_at"] = now.isoformat()
        if action == "ready":
            state["pickup_reminder_at"] = (now + timedelta(hours=48)).isoformat()
            state["pickup_due_at"] = (now + timedelta(days=7)).isoformat()
        return state
    proof = command.get("proof")
    keys = {"watch_id", "recipient", "condition", "accessories", "location", "address",
            "received_at", "signed_handoff", "source"}
    if not isinstance(proof, dict) or set(proof) != keys:
        raise CustodyError("invalid")
    if any(not isinstance(proof[k], str) or not 1 <= len(proof[k]) <= 1000 for k in
           ("watch_id", "recipient", "condition", "location", "address", "received_at", "source")):
        raise CustodyError("invalid")
    accessories = proof["accessories"]
    if not isinstance(accessories, list) or len(accessories) > 50 or any(
        not isinstance(item, str) or not 1 <= len(item) <= 100 for item in accessories
    ) or len(set(accessories)) != len(accessories):
        raise CustodyError("invalid")
    received = instant(proof["received_at"])
    if received > now or proof["signed_handoff"] is not True:
        raise CustodyError("invalid")
    if proof["source"] not in {"buyer_acknowledgement", "approved_proof"}:
        raise CustodyError("denied")
    if proof["source"] == "buyer_acknowledgement":
        if action != "buyer_receipt" or command["actor_id"] != facts.buyer_id:
            raise CustodyError("denied")
        received = now
    elif (facts.approved_proof_operation != command["operation_id"]
          or facts.approved_proof_digest != proof_digest(proof)):
        raise CustodyError("denied")
    if action == "job_intake":
        if (facts.route != "job" or not facts.job_organization_id or not facts.intake_recipient
                or command["organization_id"] != facts.job_organization_id or state["job_intake_receipt_id"]):
            raise CustodyError("denied")
        recipient = facts.intake_recipient
    elif action == "expert_receipt":
        if (facts.route != "private" or not facts.expert_independent or not facts.expert_id
                or facts.assignment_revision is None):
            raise CustodyError("denied")
        if facts.expert_id == facts.seller_id or command["actor_id"] != facts.expert_id:
            raise CustodyError("denied")
        recipient = facts.expert_id
    elif action == "return_receipt":
        if facts.route != "private" or facts.inspection != "failed" or not facts.inspection_current:
            raise CustodyError("denied")
        if not state["expert_receipt_id"] or facts.expert_receipt_id != state["expert_receipt_id"]:
            raise CustodyError("denied")
        if not facts.collection_confirmed:
            return hold("collection_pending")
        if not facts.collection_operation_id or facts.collection_revision is None:
            raise CustodyError("unavailable")
        if not facts.return_instruction:
            return hold("return_instruction_pending")
        recipient = facts.seller_id
    else:
        if facts.route == "private" and not current_private_pass(facts, state):
            raise CustodyError("denied")
        if facts.route in {"dealer", "brand"} and not facts.business_assurance_current:
            raise CustodyError("denied")
        if facts.route == "job":
            people = (facts.quality_reviewer_id, facts.assessor_id, facts.approver_id)
            if (not facts.quality_current_pass or facts.quality_revision is None or not all(people)
                    or len(set(people)) != 3 or not state["job_intake_receipt_id"]
                    or facts.job_intake_receipt_id != state["job_intake_receipt_id"]):
                raise CustodyError("denied")
        recipient = proof["recipient"] if proof["recipient"] in facts.recipients else None
    if proof["watch_id"] != facts.watch_id:
        return hold("wrong_watch")
    if proof["recipient"] != recipient:
        return hold("wrong_recipient")
    if set(accessories) != set(facts.accessories):
        return hold("missing_accessories")
    if proof["condition"] != facts.condition:
        return hold("condition")
    if proof["address"] != facts.address:
        raise CustodyError("denied")
    if state.get("last_receipt_at") and received < instant(state["last_receipt_at"]):
        raise CustodyError("stale")
    state["from_actor"] = state["custodian"]
    state["to_actor"] = recipient
    state["receipt_id"] = command["operation_id"]
    state["location"] = proof["location"]
    state["inspection_revision"] = facts.inspection_revision
    state["assignment_revision"] = facts.assignment_revision
    state["quality_revision"] = facts.quality_revision
    state["custodian"] = recipient
    state["last_receipt_at"] = received.isoformat()
    state["proof"] = {**proof, "received_at": received.isoformat()}
    if action == "expert_receipt":
        if state["expert_receipt_id"]:
            raise CustodyError("denied")
        state.update(state="expert_received", expert_receipt_id=command["operation_id"],
                     expert_custodian=facts.expert_id, expert_watch_revision=facts.watch_revision,
                     expert_assignment_revision=facts.assignment_revision,
                     expert_decision_due_at=expert_deadline(received).isoformat())
    elif action == "job_intake":
        state.update(state="job_received", job_intake_receipt_id=command["operation_id"])
    elif action == "return_receipt":
        state["state"] = "returned"
        state["restrict_new_private_publication"] = False
        state["collection_operation_id"] = facts.collection_operation_id
        state["collection_revision"] = facts.collection_revision
    else:
        hours = 72 if facts.route == "private" else 168
        state.update(state="received", buyer_received_at=received.isoformat(), window_hours=hours,
                     dispute_deadline=(received + timedelta(hours=hours)).isoformat())
    return state


def window_open(state: dict, now: datetime) -> bool:
    return bool(state.get("dispute_deadline") and now < instant(state["dispute_deadline"]))
