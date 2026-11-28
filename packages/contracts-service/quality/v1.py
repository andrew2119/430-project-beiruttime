"""Versioned private quality boundary."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, AwareDatetime, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Binding(Model):
    job_id: UUID
    watch_id: UUID
    organization_id: UUID
    scope_revision: StrictInt = Field(ge=1)
    work_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)


class Check(Model):
    key: str = Field(min_length=1, max_length=120, pattern=r'^\S.*')
    actual: str = Field(min_length=1, max_length=2000, pattern=r'^\S.*')
    satisfactory: StrictBool


class Line(Model):
    line_id: UUID
    tests: tuple[Check, ...] = Field(min_length=1, max_length=30)
    condition: Check
    fit: Check
    returned_parts: Check

    @model_validator(mode='after')
    def unique_tests(self):
        if len({test.key for test in self.tests}) != len(self.tests):
            raise ValueError('duplicate_test')
        return self


class Record(Binding):
    schema_version: Literal['quality.v1'] = 'quality.v1'
    operation_id: UUID
    actor_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    lines: tuple[Line, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError('duplicate_line')
        return self


class Current(Binding):
    actor_id: UUID
    assessor_id: UUID
    approver_id: UUID
    performer_ids: frozenset[UUID]
    quality_reviewer_id: UUID
    qualified: StrictBool
    assessor_qualified: StrictBool
    approver_qualified: StrictBool
    permitted: StrictBool
    seller_type: Literal['brand', 'dealer']
    required_line_ids: frozenset[UUID] = Field(min_length=1, max_length=1000)
    completed_line_ids: frozenset[UUID]
    required_tests: dict[UUID, frozenset[str]] = Field(min_length=1, max_length=1000)
    custody_current: StrictBool
    payment_held: StrictBool
    commitment_current: StrictBool
    incident_open: StrictBool
    accepted_current: StrictBool
    checked_at: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode='after')
    def interval(self):
        if set(self.required_tests) != self.required_line_ids or any(not keys or len(keys) > 30 or any(not key.strip() or len(key) > 120 for key in keys) for keys in self.required_tests.values()):
            raise ValueError('invalid_test_plan')
        if self.valid_until <= self.checked_at:
            raise ValueError('invalid_interval')
        return self


def current_matches(record: Record, current: Current, now: datetime):
    return (now.tzinfo is not None and current.checked_at <= now < current.valid_until
            and all(getattr(record, key) == getattr(current, key) for key in Binding.model_fields)
            and record.actor_id == current.actor_id == current.quality_reviewer_id
            and current.permitted and current.qualified and current.assessor_qualified and current.approver_qualified
            and len({current.assessor_id, current.approver_id, current.quality_reviewer_id}) == 3
            and current.quality_reviewer_id not in current.performer_ids)
