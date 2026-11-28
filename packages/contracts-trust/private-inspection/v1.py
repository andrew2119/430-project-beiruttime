"""Versioned private-watch inspection boundary. No evidence bytes cross this boundary."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

Revision = Annotated[StrictInt, Field(ge=1, le=2147483647)]
Minor = Annotated[StrictInt, Field(ge=0, le=9007199254740991)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Binding(Model):
    subject_id: UUID
    watch_id: UUID
    watch_revision: Revision
    actor_id: UUID
    organization_id: UUID
    assignment_revision: Revision
    quote_id: UUID
    quote_revision: Revision
    policy_revision: Revision
    source_revision: Revision


class Check(Model):
    item: Literal['identity', 'movement', 'case', 'provenance']
    verdict: Literal['passed', 'failed', 'inconclusive']


class Submit(Binding):
    schema_version: Literal['private-inspection.v1']
    operation_id: UUID
    expected_revision: Annotated[StrictInt, Field(ge=0, le=2147483646)]
    custody_receipt_id: UUID
    checklist_revision: Revision
    checklist: Annotated[tuple[Check, ...], Field(min_length=4, max_length=4)]
    evidence_refs: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=12)]
    result: Literal['passed', 'failed', 'inconclusive']
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class Receipt(Binding):
    schema_version: Literal['private-inspection.v1']
    operation_id: UUID
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    state: Literal['passed', 'failed', 'inconclusive']
    revision: Revision
    result_revision: Revision
    custody_receipt_id: UUID
    checklist_revision: Revision
    payment_operation_id: UUID
    payment_revision: Revision
    proof_revision: Revision
    recorded_at: datetime
    pending_reason: str | None
    next_actor: str | None
    next_review_at: datetime | None


class CurrentResult(Receipt):
    inspection_prerequisite_passed: StrictBool
    buyer_handover_blocked: StrictBool
    seller_payout_blocked: StrictBool
    seller_charge_required: StrictBool
    buyer_watch_price_refund_ready: StrictBool
    refundable_watch_price_minor: Minor
    refundable_fee_minor: Literal[0]
    currency: Literal['USD']
    charge_operation_id: UUID | None
    charge_amount_minor: Minor
    private_publication_restricted: StrictBool
    return_blocked: StrictBool


class Source(Binding):
    """Current provider facts, never a browser claim or a cached projection."""
    seller_id: UUID
    buyer_id: UUID
    expert_id: UUID
    expert_independent: StrictBool
    authorized: StrictBool
    seller_kind: Literal['private', 'dealer', 'brand']
    commitment_current: StrictBool
    payment_state: Literal['paid_held', 'pending', 'unpaid']
    payment_operation_id: UUID
    payment_revision: Revision
    custody_receipt_id: UUID
    custody_watch_revision: Revision
    custody_to_actor: UUID
    authorized_recipient: UUID
    received_at: datetime
    custody_current: StrictBool
    incident_open: StrictBool
    proof_revision: Revision
    checklist_revision: Revision
    evidence_refs: Annotated[tuple[UUID, ...], Field(max_length=12)]
    currency: Literal['USD']
    price_minor: Minor
    buyer_fee_minor: Minor
    seller_commission_minor: Minor
    return_trip_minor: Minor
    return_line_accepted: StrictBool
    saved_simulated_method_id: UUID
    checked_at: datetime
    valid_until: datetime


class Collection(Model):
    operation_id: UUID
    watch_id: UUID
    watch_revision: Revision
    source_revision: Revision
    result_revision: Revision
    assignment_revision: Revision
    custody_receipt_id: UUID
    subject_id: UUID
    seller_id: UUID
    method_id: UUID
    currency: Literal['USD']
    amount_minor: Minor
    state: Literal['confirmed', 'pending', 'unknown', 'declined']
    custody_instruction_id: UUID | None
    checked_at: datetime
    valid_until: datetime


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('utc_required')
    return value.astimezone(timezone.utc)


def fresh(checked_at: datetime, valid_until: datetime, now: datetime) -> bool:
    return utc(checked_at) <= utc(now) < utc(valid_until)
