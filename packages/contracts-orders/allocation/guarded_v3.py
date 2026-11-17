"""Exact private command bindings for the sole Orders transaction boundary."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictInt, model_validator
from bt_contracts_core.models import Contract
from bt_contracts.orders.journal.v2 import AcceptedMoney

Revision = StrictInt


class Binding(Contract):
    schema_version: Literal["orders-commitment.v3"] = "orders-commitment.v3"
    operation_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    actor_id: UUID
    organization_id: UUID | None
    order_id: UUID
    watch_id: UUID
    expected_revision: Revision = Field(ge=1)
    source_id: UUID
    source_revision: Revision = Field(ge=1)
    quote_id: UUID
    quote_revision: Revision = Field(ge=1)
    policy_revision: Revision = Field(ge=1)


class JobBinding(Binding):
    kind: Literal["job"] = "job"
    order_kind: Literal["service_job", "customization_job"]
    buyer_id: UUID
    request_id: UUID
    request_revision: Revision = Field(ge=1)
    assessment_id: UUID
    assessment_revision: Revision = Field(ge=1)
    consent_revision: Revision = Field(ge=1)
    grant_id: UUID
    grant_revision: Revision = Field(ge=1)
    accepted_terms_revision: Revision = Field(ge=1)
    accepted_line_ids: list[UUID] = Field(min_length=1, max_length=100)
    currency: Literal["USD"] = "USD"
    total_minor: StrictInt = Field(gt=0, le=9_000_000_000_000)

    @model_validator(mode="after")
    def business_and_lines(self):
        if self.organization_id is None or len(set(self.accepted_line_ids)) != len(self.accepted_line_ids):
            raise ValueError("A current business and distinct accepted lines are required")
        return self


class FinancialCommand(Binding):
    kind: Literal["refund", "release"]
    recipient_id: UUID
    amount_minor: StrictInt = Field(gt=0, le=9_000_000_000_000)
    currency: Literal["USD"] = "USD"
    receipt_id: UUID | None = None
    receipt_revision: Revision | None = Field(ge=1, default=None)
    refund_basis: Literal["controlled_return", "pre_dispatch", "failure_exception"] | None = None
    dispute_revision: Revision = Field(ge=1)
    incident_revision: Revision = Field(ge=1)

    @model_validator(mode="after")
    def receipt_basis(self):
        if (self.receipt_id is None) != (self.receipt_revision is None):
            raise ValueError("Receipt identity and revision belong together")
        if self.kind == "release":
            if self.receipt_id is None or self.refund_basis is not None:
                raise ValueError("Release requires actual receipt and no refund exception")
        elif self.refund_basis not in {"pre_dispatch", "failure_exception"} and self.receipt_id is None:
            raise ValueError("A controlled return requires actual receipt")
        return self


class CustodyCommand(Binding):
    kind: Literal["custody"] = "custody"
    watch_revision: Revision = Field(ge=1)
    from_actor: UUID
    to_actor: UUID
    authorized_recipient: UUID
    condition: str = Field(min_length=1, max_length=2000)
    accessories: list[str] = Field(max_length=100)
    location: str = Field(min_length=1, max_length=500)
    received_at: AwareDatetime
    proof_revision: Revision = Field(ge=1)
    incident_revision: Revision = Field(ge=1)

    @model_validator(mode="after")
    def actual_receipt(self):
        if (self.to_actor != self.authorized_recipient or self.from_actor == self.to_actor
                or not self.condition.strip() or not self.location.strip()
                or any(not item.strip() or len(item) > 200 for item in self.accessories)):
            raise ValueError("An actual authorized custody receipt is required")
        return self


class CurrentDecision(Contract):
    """Produced under the same transaction by current authority, never a projection."""

    binding: FinancialCommand | CustodyCommand
    state: Literal["authorized", "denied", "pending"]
    revision: Revision = Field(ge=1)
    next_actor: UUID
    next_review_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=200)


class GuardedResult(Contract):
    operation_key: str
    status: Literal["succeeded", "denied", "pending"]
    revision: Revision = Field(ge=1)
    code: str
    message_en: str
    message_ar: str
    next_actor: UUID
    next_review_at: AwareDatetime
    payment_authority: Literal[False] = False
    simulated: Literal[True] = True


class CurrentJobDecision(Contract):
    binding: JobBinding
    state: Literal["authorized", "denied", "pending"]
    seller_id: UUID
    seller_type: Literal["dealer", "brand"]
    money: AcceptedMoney
    next_actor: UUID
    next_review_at: AwareDatetime

    @model_validator(mode="after")
    def retained_job(self):
        if (self.money.order_kind != self.binding.order_kind
                or self.money.payable_minor != self.binding.total_minor
                or self.money.currency != self.binding.currency):
            raise ValueError("The exact retained job economics are required")
        return self
