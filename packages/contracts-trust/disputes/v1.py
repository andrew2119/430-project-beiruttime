"""Private dispute commands. All money is retained USD principal in cents."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Evidence(Contract):
    reference: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,128}$')
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    size: StrictInt = Field(ge=1, le=5_000_000)
    media_type: Literal['image/jpeg', 'image/png', 'application/pdf']


class Command(Contract):
    schema_version: Literal['disputes.v1'] = 'disputes.v1'
    operation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,128}$')
    subject_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,128}$')
    organization_id: str | None = Field(default=None, max_length=128)
    expected_revision: StrictInt = Field(ge=0, le=2_147_483_647)
    source_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=0)
    kind: Literal['open', 'respond', 'refund', 'release']
    reason: str = Field(min_length=3, max_length=4000)
    evidence: tuple[Evidence, ...] = Field(default=(), max_length=5)
    amount_minor: StrictInt = Field(default=0, ge=0, le=9_007_199_254_740_991)

    @field_validator('reason')
    @classmethod
    def reason_required(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('reason_required')
        return value.strip()


class Result(Contract):
    schema_version: Literal['disputes.v1'] = 'disputes.v1'
    operation_id: str
    subject_id: str
    watch_id: str
    actor_id: str
    organization_id: str | None
    expected_revision: int
    state: Literal['hold_pending', 'open', 'responded', 'refund_pending', 'release_pending', 'refunded', 'released', 'denied']
    revision: int
    pending_reason: str | None
    next_actor: str
    next_action: str
    next_review_at: datetime
    closing_at: datetime
    financial_operation_id: str | None
    amount_minor: int
    currency: Literal['USD'] = 'USD'
