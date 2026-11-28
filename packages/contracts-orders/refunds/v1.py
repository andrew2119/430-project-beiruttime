"""Private refund command and current-source contract, version one."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, AwareDatetime, model_validator

MAX_MINOR = 9_000_000_000_000_000
Money = StrictInt


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Command(Record):
    schema_version: Literal['refunds.v1'] = 'refunds.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=1)
    source_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    basis_id: UUID
    amount_minor: Money = Field(gt=0, le=MAX_MINOR)
    currency: Literal['USD'] = 'USD'


class Line(Record):
    line_id: UUID
    amount_minor: Money = Field(ge=0, le=MAX_MINOR)
    kind: Literal['labor', 'part', 'assessment', 'transport']
    accepted: StrictBool
    performed_or_consumed: StrictBool
    unused_returnable: StrictBool


class Facts(Record):
    """Read inside the Orders journal fence, never from a view or cache."""
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    buyer_id: UUID
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    revision: StrictInt = Field(ge=1)
    source_revision: StrictInt = Field(ge=1)
    basis_id: UUID
    kind: Literal['watch', 'job']
    basis: Literal['failed_authentication', 'cancellation', 'dispute', 'partial_work']
    basis_approved: StrictBool
    payment_state: Literal['paid_held', 'pending', 'unpaid', 'released']
    basis_valid_until: AwareDatetime
    paid_principal_minor: Money = Field(ge=0, le=MAX_MINOR)
    retained_principal_minor: Money = Field(ge=0, le=MAX_MINOR)
    approved_minor: Money = Field(ge=0, le=MAX_MINOR)
    confirmed_minor: Money = Field(ge=0, le=MAX_MINOR)
    unresolved_minor: Money = Field(ge=0, le=MAX_MINOR)
    business_fee_minor: Money = Field(ge=0, le=MAX_MINOR)
    custody_transferred: StrictBool
    controlled_return_received: StrictBool
    recorded_failure_exception: StrictBool
    private_sale: StrictBool
    failed_inspection: StrictBool
    lines: tuple[Line, ...] = Field(max_length=200)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError('duplicate_line')
        return self


class Authority(Record):
    actor_id: UUID
    organization_id: UUID
    subject_id: UUID
    watch_id: UUID
    can_refund: StrictBool
    current_assignment: StrictBool


class Plan(Record):
    command: Command
    buyer_id: UUID
    cap_minor: Money = Field(ge=0, le=MAX_MINOR)
    business_fee_receivable_minor: Money = Field(ge=0, le=MAX_MINOR)
    fee_collection_key: str = Field(max_length=100)
    recorded_at: AwareDatetime
    next_review_at: AwareDatetime


class Operation(Record):
    schema_version: Literal['refunds.v1'] = 'refunds.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=1)
    state: Literal['pending', 'confirmed', 'declined']
    revision: StrictInt = Field(ge=1)
    pending_reason: Literal['reconciliation', 'processing'] | None
    next_actor: Literal['payout_operator'] | None
    next_review_at: AwareDatetime | None
    amount_minor: Money = Field(gt=0, le=MAX_MINOR)
    currency: Literal['USD'] = 'USD'
    simulated: Literal[True] = True

    @model_validator(mode='after')
    def recovery(self):
        pending = self.state == 'pending'
        if pending != all(value is not None for value in (
            self.pending_reason, self.next_actor, self.next_review_at
        )) or (not pending and any(value is not None for value in (
            self.pending_reason, self.next_actor, self.next_review_at
        ))):
            raise ValueError('invalid_recovery')
        return self
