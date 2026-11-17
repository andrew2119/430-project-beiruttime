"""Versioned private visit commands. A booking conveys no custody or work permission."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

Purpose = Literal['intake', 'assessment', 'fit', 'collection']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Command(Contract):
    schema_version: Literal['appointments.v1'] = 'appointments.v1'
    operation_id: UUID
    appointment_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    assignment_revision: StrictInt = Field(ge=1)
    source_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    quote_id: UUID | None = None
    quote_revision: StrictInt | None = Field(default=None, ge=1)
    kind: Literal['request', 'confirm', 'reschedule', 'cancel']
    purpose: Purpose
    civil_time: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$')
    timezone: Literal['Asia/Beirut'] = 'Asia/Beirut'
    selected_instant: AwareDatetime | None = None
    repeated_time_confirmed: StrictBool = False
    duration_minutes: StrictInt = Field(ge=15, le=120)

    @model_validator(mode='after')
    def bindings(self):
        datetime.strptime(self.civil_time, '%Y-%m-%dT%H:%M')
        if (self.quote_id is None) != (self.quote_revision is None):
            raise ValueError('quote_binding')
        if (self.kind == 'request') != (self.expected_revision == 0):
            raise ValueError('revision_binding')
        return self


class Authority(Contract):
    actor_id: UUID
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    source_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    quote_id: UUID | None = None
    quote_revision: StrictInt | None = Field(default=None, ge=1)
    role: Literal['buyer', 'business']
    record_allowed: StrictBool
    active: StrictBool
    onboarded: StrictBool
    business_kind: Literal['brand', 'dealer']
    purposes: tuple[Purpose, ...]
    assignment_revision: StrictInt = Field(ge=1)


class Visit(Contract):
    schema_version: Literal['appointments.v1'] = 'appointments.v1'
    appointment_id: UUID
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: int
    source_revision: int
    policy_revision: int
    quote_id: UUID | None
    quote_revision: int | None
    purpose: Purpose
    civil_time: str
    timezone: Literal['Asia/Beirut'] = 'Asia/Beirut'
    instant: AwareDatetime
    duration_minutes: int
    repeated_time_confirmed: bool
    state: Literal['requested', 'confirmed', 'cancelled']
    revision: int
    confirmed_by: UUID | None
    assignment_revision: int
    pending_reason: Literal['business_confirmation'] | None
    next_actor: Literal['business', 'none']
    next_review_at: AwareDatetime | None
    custody_received: Literal[False] = False
    work_authorized: Literal[False] = False
    physical_release_allowed: Literal[False] = False
