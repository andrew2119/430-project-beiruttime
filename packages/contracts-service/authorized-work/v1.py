"""Versioned private work boundary; Orders remains execution authority."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, StrictInt, field_validator

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    @field_validator('*', mode='after')
    @classmethod
    def utc_instants(cls, value):
        return value.astimezone(timezone.utc) if isinstance(value, datetime) else value

class Part(Contract):
    line_id: UUID
    reference: str = Field(min_length=1, max_length=160)
    quantity: StrictInt = Field(ge=1, le=1000)
    disposition: Literal['installed', 'consumed', 'removed_return', 'unused_return']

class Reading(Contract):
    phase: Literal['before', 'after']
    observed_at: AwareDatetime
    seconds_per_day: StrictInt = Field(ge=-86400, le=86400)
    method: str = Field(min_length=1, max_length=160)

class Command(Contract):
    schema_version: Literal['authorized-work.v1']
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    source_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    kind: Literal['progress', 'material_change', 'loss', 'damage', 'waiting_parts', 'waiting_customer', 'declined_return']
    line_ids: tuple[UUID, ...] = Field(max_length=100)
    parts: tuple[Part, ...] = Field(max_length=100)
    readings: tuple[Reading, ...] = Field(max_length=20)
    note: str = Field(min_length=1, max_length=2000)
    observed_at: AwareDatetime
    next_actor: UUID
    next_action: str = Field(min_length=1, max_length=500)
    next_review_at: AwareDatetime

class Authority(Contract):
    actor_id: UUID
    organization_id: UUID
    subject_id: UUID
    watch_id: UUID
    source_revision: StrictInt
    quote_id: UUID
    quote_revision: StrictInt
    policy_revision: StrictInt
    accepted_line_ids: tuple[UUID, ...] = Field(max_length=100)
    responsible_actor_id: UUID
    required_line_ids: tuple[UUID, ...] = Field(max_length=100)
    state: Literal['authorized', 'declined', 'denied']
    valid_until: AwareDatetime
    custody_current: Literal[True]
    payment_state: Literal['paid_held', 'pending', 'unpaid']
    commitment_current: Literal[True]

    @field_validator('custody_current','commitment_current',mode='before')
    @classmethod
    def exact_authority(cls, value):
        if value is not True:
            raise ValueError('Current authority required')
        return value

class HoldReceipt(Contract):
    actor_id: UUID
    organization_id: UUID
    quote_id: UUID
    quote_revision: StrictInt
    policy_revision: StrictInt
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    source_revision: StrictInt
    state: Literal['held']
    work_held: Literal[True]
    handover_held: Literal[True]
    payout_held: Literal[True]
    invalidates_quality: Literal[True]
    hold_revision: StrictInt = Field(ge=1)


    @field_validator('work_held','handover_held','payout_held','invalidates_quality',mode='before')
    @classmethod
    def exact_hold(cls, value):
        if value is not True:
            raise ValueError('Durable hold required')
        return value


class Operation(Contract):
    schema_version: Literal['authorized-work.v1']
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    source_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    state: Literal['recorded', 'pending', 'paused']
    revision: StrictInt = Field(ge=1)
    pending_reason: Literal['orders_hold', 'hold_conflict'] | None
    next_actor: UUID
    next_review_at: AwareDatetime
    recorded_at: AwareDatetime
    since: AwareDatetime
    escalation_at: AwareDatetime
    release_eligible: Literal[False]
    hold_revision: StrictInt | None = Field(default=None, ge=1)
