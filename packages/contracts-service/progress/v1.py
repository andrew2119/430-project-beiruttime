"""Versioned progress facts. These facts never authorize execution or release."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator, field_validator


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Binding(Record):
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    source_revision: StrictInt = Field(ge=1)
    scope_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)


class AcceptedLine(Record):
    line_id: UUID
    required: StrictBool
    title_en: str = Field(min_length=1, max_length=300)
    title_ar: str = Field(min_length=1, max_length=300)
    amount_minor: StrictInt = Field(ge=0, le=999999999999)


class Source(Binding):
    buyer_id: UUID
    assigned_actor_ids: tuple[UUID, ...] = Field(max_length=100)
    accepted_lines: tuple[AcceptedLine, ...] = Field(max_length=1000)
    currency: Literal['USD']
    commitment_current: StrictBool
    custody_current: StrictBool
    payment_held: StrictBool
    scope_accepted: StrictBool
    incident_open: StrictBool
    material_line_ids: tuple[UUID, ...] = Field(max_length=1000)
    quality_result: Literal['missing', 'failed', 'passed']
    quality_work_revision: StrictInt = Field(ge=0)
    quality_scope_revision: StrictInt = Field(ge=0)
    quality_independent: StrictBool
    responsible_actor_id: UUID
    next_action_en: str = Field(min_length=1, max_length=1000)
    next_action_ar: str = Field(min_length=1, max_length=1000)
    next_review_at: AwareDatetime
    authority_until: AwareDatetime

    @model_validator(mode='after')
    def unique_lines(self):
        ids = [line.line_id for line in self.accepted_lines]
        if len(set(ids)) != len(ids) or not set(self.material_line_ids).issubset(ids):
            raise ValueError('Invalid line scope')
        return self

    @field_validator('authority_until', 'next_review_at')
    @classmethod
    def utc(cls, value):
        if value.utcoffset().total_seconds() != 0:
            raise ValueError('UTC required')
        return value


class Access(Record):
    actor_id: UUID
    organization_id: UUID | None
    can_read: StrictBool
    can_write: StrictBool


class Command(Binding):
    schema_version: Literal['service.progress.v1'] = 'service.progress.v1'
    operation_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    line_id: UUID
    state: Literal['not_started', 'working', 'waiting_parts', 'waiting_buyer', 'completed', 'rework']
    step_en: str = Field(min_length=1, max_length=1000)
    step_ar: str = Field(min_length=1, max_length=1000)
    parts_en: str = Field(max_length=1000)
    parts_ar: str = Field(max_length=1000)
    readings_en: str = Field(max_length=1000)
    readings_ar: str = Field(max_length=1000)
    estimate_start: AwareDatetime | None
    estimate_end: AwareDatetime | None
    estimate_basis_en: str = Field(max_length=1000)
    estimate_basis_ar: str = Field(max_length=1000)
    next_actor: UUID
    next_review_at: AwareDatetime
    follow_up: Literal['review', 'contact', 'alternative_review', 'cancellation_review', 'controlled_handback']

    @model_validator(mode='after')
    def estimates(self):
        if (self.estimate_start is None) != (self.estimate_end is None):
            raise ValueError('Both range bounds required')
        if self.estimate_start is not None:
            if self.estimate_end < self.estimate_start or not self.estimate_basis_en.strip() or not self.estimate_basis_ar.strip():
                raise ValueError('An ordered range and bilingual basis are required')
        for value in (self.estimate_start, self.estimate_end, self.next_review_at):
            if value and value.utcoffset().total_seconds() != 0:
                raise ValueError('UTC required')
        for value in (self.step_en, self.step_ar):
            if not value.strip():
                raise ValueError('Actual step required')
        return self


def instant(value: datetime) -> str:
    return value.isoformat()
