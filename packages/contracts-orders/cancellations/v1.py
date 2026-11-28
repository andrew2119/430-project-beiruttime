"""Private cancellation commands; consent withdrawal is a separate operation."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, model_validator
from bt_contracts_core.models import Contract

Minor = Field(ge=0, le=9007199254740991)


class Command(Contract):
    schema_version: Literal[1] = 1
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt = Field(ge=1)
    action: Literal['request', 'accept', 'decline']
    reason: str = Field(min_length=1, max_length=500)


class Facts(Contract):
    """Current serialized source facts, never a browser projection."""
    subject_id: UUID
    watch_id: UUID
    buyer_id: UUID
    organization_id: UUID | None
    revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    kind: Literal['watch', 'job']
    payment: Literal['unpaid', 'pending', 'unknown', 'paid_held', 'released']
    attempts: list[Literal['declined', 'pending', 'unknown', 'confirmed']] = Field(max_length=1000)
    principal_minor: StrictInt = Minor
    collected_fee_minor: StrictInt = Minor
    refundable_labor_minor: StrictInt = Minor
    unused_returnable_parts_minor: StrictInt = Minor
    reserved_refund_minor: StrictInt = Minor
    confirmed_refund_minor: StrictInt = Minor
    work_started: bool
    parts_consumed: bool
    dispatched: bool
    custody_transferred: bool
    return_state: Literal['none', 'pending', 'verified', 'mismatch']
    failure_exception_id: UUID | None
    cancellation_state: Literal['none', 'pending', 'accepted', 'declined']
    responsible_actor: UUID
    escalation_actor: UUID
    hold_started_at: AwareDatetime | None
    last_progress_at: AwareDatetime | None

    @model_validator(mode='after')
    def retained_hold_timing(self):
        if (self.cancellation_state == 'pending' or (
                self.cancellation_state == 'accepted' and self.payment != 'unpaid'
        )) and self.hold_started_at is None:
            raise ValueError('retained hold timing required')
        if self.last_progress_at is not None and (
                self.hold_started_at is None or self.last_progress_at < self.hold_started_at):
            raise ValueError('progress must follow hold start')
        return self


class Result(Contract):
    schema_version: Literal[1] = 1
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt
    revision: StrictInt
    state: Literal['accepted', 'declined', 'pending', 'denied']
    pending_reason: str | None
    next_actor: UUID | None
    next_review_at: AwareDatetime | None
    effect: Literal['none', 'release_commitment', 'pause_fulfilment']
    refundable_minor: StrictInt = Minor
    completed: bool = False
    hold_started_at: AwareDatetime | None = None
    last_progress_at: AwareDatetime | None = None
    escalation_at: AwareDatetime | None = None
    review_overdue: bool = False
    escalated: bool = False
