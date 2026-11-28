"""Current decision source bindings and deterministic development fixtures."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt

SCHEMA_VERSION = "brand-decisions.current.v3"
OPERATIONS = {
    "quote": "GET /internal/v3/quotes/{id}/validation?buyer_id={buyer_id}",
    "prepare": "POST /internal/v1/grants/prepare",
    "consume": "POST /internal/v1/grants/consume",
    "lookup": "GET /v2/brand-decision-operations/{operation_id}",
    "recovery": "POST /v2/brand-decision-operations/{operation_id}/recovery",
    "resume": "POST /v2/brand-decision-operations/{operation_id}/resume",
}


def fixture(case="success"):
    """Synthetic current facts; these never establish connected permission."""
    def identifier(number):
        return str(UUID(int=number))

    row = {"id": identifier(1), "revision": 1, "brand_id": identifier(2), "buyer_id": identifier(3), "watch_id": identifier(20)}
    common = {"request_id": row["id"], "request_revision": 1, "brand_id": row["brand_id"], "revision": 1}
    assessment = {
        **common, "id": identifier(4), "status": "feasible", "current": True, "qualified": True,
        "assessor_id": identifier(5), "approver_id": identifier(6), "assignment_revision": 1,
        "approval_assignment_current": True,
    }
    quote = {
        **common, "id": identifier(7), "status": "accepted", "buyer_id": row["buyer_id"],
        "assessment_id": assessment["id"], "assessment_revision": 1, "total_minor": 500000,
        "currency": "USD", "expires_at": None,
    }
    grant = {
        **common, "id": identifier(8), "subject_id": row["buyer_id"], "purpose": "brand_approval",
        "watch_id": row["watch_id"], "quote_id": quote["id"], "quote_revision": 1, "amount_minor": 500000, "currency": "USD",
        "status": "valid", "current": True, "reviewer_id": identifier(9), "consent_status": "active",
        "consent_revision": 1, "revoked_at": None, "expires_at": "2026-11-17T00:00:00Z",
    }
    values = {"assessment": assessment, "quote": quote, "grant": grant}
    intent = {kind + suffix: value[field] for kind, value in values.items()
              for suffix, field in (("_id", "id"), ("_revision", "revision"))}
    if case == "denied":
        grant["consent_status"] = "withdrawn"
    elif case == "stale":
        quote["revision"] = 2
    elif case not in ("success", "lost_response"):
        raise ValueError("Unknown fixture")
    return deepcopy({"schema_version": SCHEMA_VERSION, "row": row, "values": values, "intent": intent,
                     "approver_id": identifier(6), "now": datetime(2026, 11, 16, tzinfo=timezone.utc),
                     "state": "pending" if case == "lost_response" else "not_decided"})


class RetainedBindings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    watch_id: UUID | None = None
    consent_revision: StrictInt | None = Field(default=None, ge=1)
    assignment_revision: StrictInt | None = Field(default=None, ge=1)
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    brand_id: UUID
    subject_id: UUID
    approver_id: UUID
    assessment_id: UUID
    assessment_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    grant_id: UUID
    grant_revision: StrictInt = Field(ge=1)
    amount_minor: StrictInt = Field(ge=1, le=18_000_000_000_000)
    currency: Literal["USD", "LBP"]
    purpose: Literal["brand_approval"]


class CurrentBindings(RetainedBindings):
    watch_id: UUID
    currency: Literal["USD"]
    consent_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=1)


class CurrentOperation(BaseModel):
    """Exact public lookup/resume response; the identifier is the stable operation."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["brand-decisions.current.v3"]
    operation_id: UUID
    subject_id: UUID | None
    watch_id: UUID | None
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=1)
    state: Literal["pending", "approved", "rejected", "denied"]
    revision: StrictInt = Field(ge=1)
    pending_reason: Literal["authority_unconfirmed"] | None
    next_actor: UUID | None
    next_action: Literal["reconcile_operation", "respond_to_operation", "escalate_operation", "restore_recovery"] | None
    next_review_at: AwareDatetime | None
    escalate_at: AwareDatetime | None
    id: UUID
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    brand_id: UUID
    actor_id: UUID
    status: Literal["pending", "approved", "rejected", "denied"]
    reason: str = Field(min_length=3, max_length=1000)
    bindings: CurrentBindings | RetainedBindings | None
    code: str | None
    confirmed_at: AwareDatetime | None
    execution_authority: Literal[False]
