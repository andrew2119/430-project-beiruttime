"""Bounded external cleaning; no opening, polishing or movement service."""
from datetime import timezone
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Binding(Model):
    schema_version: Literal['cleaning.v1'] = 'cleaning.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0, le=2147483646)
    source_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)


class Command(Binding):
    action: Literal['request', 'accept']
    areas: list[Literal['case', 'bracelet']] = Field(min_length=1, max_length=2)
    condition: str = Field(min_length=1, max_length=2000)
    preservation_limits: str = Field(min_length=1, max_length=2000)
    assessment_permission: Literal[True]
    no_submersion_promise: Literal[True]
    no_movement_service: Literal[True]
    quote_id: UUID | None = None
    quote_revision: StrictInt | None = Field(default=None, ge=1)
    terms_revision: StrictInt | None = Field(default=None, ge=1)

    @field_validator('assessment_permission', 'no_submersion_promise', 'no_movement_service', mode='before')
    @classmethod
    def explicit_acknowledgement(cls, value):
        if value is not True:
            raise ValueError('Explicit acknowledgement required')
        return value

    @field_validator('areas')
    @classmethod
    def unique_areas(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Duplicate area')
        return sorted(value)

    @field_validator('condition', 'preservation_limits')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Meaningful text required')
        return value.strip()


class Quote(Model):
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    request_revision: StrictInt = Field(ge=1)
    request_id: UUID
    assessment_id: UUID
    assessment_revision: StrictInt = Field(ge=1)
    assessor_id: UUID
    approver_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    capability_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    watch_id: UUID
    organization_id: UUID
    line_id: UUID
    scope: Literal['external_case_bracelet_cleaning']
    areas: list[Literal['case', 'bracelet']] = Field(min_length=1, max_length=2)
    process: str = Field(min_length=1, max_length=2000)
    limitations: str = Field(min_length=1, max_length=2000)
    condition: str = Field(min_length=1, max_length=2000)
    preservation_limits: str = Field(min_length=1, max_length=2000)
    lead_time: str = Field(min_length=1, max_length=1000)
    terms: str = Field(min_length=1, max_length=4000)
    terms_revision: StrictInt = Field(ge=1)
    currency: Literal['USD']
    base_minor: StrictInt = Field(ge=0, le=999999999999)
    buyer_fee_minor: StrictInt = Field(ge=0, le=0)
    business_fee_minor: StrictInt = Field(ge=0, le=999999999999)
    total_minor: StrictInt = Field(ge=0, le=999999999999)
    expires_at: AwareDatetime | None
    accepted_at: AwareDatetime | None

    @field_validator('expires_at', 'accepted_at')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc) if value else value


class PaidReadiness(Model):
    buyer_id: UUID
    order_id: UUID
    order_kind: Literal['service']
    watch_id: UUID
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    currency: Literal['USD']
    total_minor: StrictInt = Field(ge=0, le=999999999999)
    payment_operation_id: UUID
    payment_revision: StrictInt = Field(ge=1)
    state: Literal['paid_held', 'pending', 'unpaid']


class Facts(Model):
    """Fresh authenticated, serialized provider facts, never a client payload."""
    actor_id: UUID
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    source_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    authorized: StrictBool
    supported: StrictBool
    quote: Quote | None = None
    order_id: UUID | None = None
    job_id: UUID | None = None
    commitment_id: UUID | None = None
    custody_receipt_id: UUID | None = None
    payment_operation_id: UUID | None = None
    payment_revision: StrictInt | None = Field(default=None, ge=1)
    paid_held: StrictBool = False
    payment: PaidReadiness | None = None
    custody_order_id: UUID | None = None
    custody_watch_id: UUID | None = None
    commitment_order_id: UUID | None = None
    commitment_watch_id: UUID | None = None
    current_custody: StrictBool = False
    current_consent: StrictBool = False
    incident: StrictBool = True


class Result(Binding):
    state: Literal['requested', 'accepted']
    revision: StrictInt = Field(ge=1)
    pending_reason: None = None
    next_actor: Literal['business', 'buyer']
    next_review_at: AwareDatetime
    areas: list[Literal['case', 'bracelet']]
    condition: str
    preservation_limits: str
    quote: Quote | None = None
    accepted_at: AwareDatetime | None = None
    submitted_at: AwareDatetime
