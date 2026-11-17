"""Private Orders release boundary. Amounts are integer USD cents."""
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

Minor = Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]
Revision = Annotated[int, Field(strict=True, ge=1)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Context(Model):
    actor_id: UUID
    organization_id: UUID | None


class Command(Context):
    schema_version: Literal["orders.releases.v1"] = "orders.releases.v1"
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    expected_revision: Revision
    quote_id: UUID
    quote_revision: Revision
    policy_revision: Revision
    recipient_id: UUID
    recipient_revision: Revision


class Receipt(Model):
    order_id: UUID
    watch_id: UUID
    watch_revision: Revision
    authorized_recipient: UUID
    recipient: UUID
    kind: Literal["buyer_acknowledgement", "approved_handoff", "dispatch"]
    approved: StrictBool
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("utc_required")
        return value


class Snapshot(Model):
    subject_id: UUID
    watch_id: UUID
    watch_revision: Revision
    revision: Revision
    seller_id: UUID
    buyer_id: UUID
    organization_id: UUID | None
    kind: Literal["private_watch", "dealer_watch", "brand_watch", "service", "customization"]
    quote_id: UUID
    quote_revision: Revision
    policy_revision: Revision
    currency: Literal["USD"]
    principal_minor: Minor
    buyer_fee_minor: Minor
    business_fee_minor: Minor
    total_minor: Minor
    accepted_economics: StrictBool
    accepted_fee_line: StrictBool
    payment_state: Literal["paid_held", "pending", "unpaid"]
    payment_operation_id: UUID | None
    payment_revision: Revision | None
    held_principal_minor: Minor
    refund_reserved_minor: Minor
    refunded_minor: Minor
    recipient_id: UUID
    recipient_revision: Revision
    recipient_owner_id: UUID
    recipient_verified: StrictBool
    dispute_window_hours: Annotated[int, Field(strict=True, ge=1, le=8760)]
    receipt: Receipt | None
    inspection_current: StrictBool
    inspection_pass: StrictBool
    inspection_independent: StrictBool
    inspection_actual_custody: StrictBool
    assurance_current: StrictBool
    quality_current: StrictBool
    quality_pass: StrictBool
    quality_actual_tests: StrictBool
    quality_fit_checked: StrictBool
    quality_returned_parts_checked: StrictBool
    assessor_id: UUID | None
    approver_id: UUID | None
    quality_reviewer_id: UUID | None
    hold_state: Literal["clear", "held", "unknown"]
    hold_revision: Revision
    sources_current: StrictBool
    active_release_operation_id: UUID | None
    responsible_operator_id: UUID
    responsibility_revision: Revision

    @model_validator(mode="after")
    def exact_totals(self):
        if self.total_minor != self.principal_minor + self.buyer_fee_minor:
            raise ValueError("invalid_total")
        if self.business_fee_minor > self.principal_minor:
            raise ValueError("invalid_fee")
        if self.refund_reserved_minor + self.refunded_minor > self.principal_minor:
            raise ValueError("invalid_refund")
        if self.kind in ("service", "customization") and self.buyer_fee_minor != 0:
            raise ValueError("invalid_job_surcharge")
        return self


Condition = Literal[
    "stale_revision", "binding_changed", "sources_unavailable", "economics_unaccepted",
    "payment_not_held", "principal_unavailable", "refund_active", "recipient_unverified",
    "inspection_required", "assurance_required", "quality_required", "receipt_required",
    "window_open", "hold_active", "hold_unknown", "release_exists",
]


class Operation(Command):
    state: Literal["denied", "pending", "paid_out", "unavailable"]
    revision: Revision
    missing: tuple[Condition, ...] = ()
    pending_reason: Literal["transfer_pending", "transfer_failed", "response_unknown", "dependency_unavailable"] | None = None
    next_actor: Literal["operator", "payout_operator"]
    responsible_operator_id: UUID | None
    responsibility_revision: Revision | None
    next_action: Literal["review_conditions", "reconcile_transfer", "complete"]
    next_review_at: datetime
    gross_minor: Minor | None = None
    fee_minor: Minor | None = None
    net_minor: Minor | None = None
    simulated: Literal[True] = True

    @field_validator("next_review_at")
    @classmethod
    def utc(cls, value):
        return Receipt.utc(value)

    @model_validator(mode="after")
    def reconciles(self):
        if self.pending_reason not in ("response_unknown", "dependency_unavailable") and (
            self.responsible_operator_id is None or self.responsibility_revision is None
        ):
            raise ValueError("responsible_operator_required")
        money = (self.gross_minor, self.fee_minor, self.net_minor)
        if any(v is not None for v in money):
            if any(v is None for v in money) or self.gross_minor != self.fee_minor + self.net_minor:
                raise ValueError("invalid_release_totals")
        if self.state == "paid_out" and (self.net_minor is None or self.missing or self.pending_reason):
            raise ValueError("invalid_paid_out")
        return self


class Preview(Model):
    snapshot: Snapshot
    missing: tuple[Condition, ...]
    closes_at: datetime | None
    simulated: Literal[True] = True
