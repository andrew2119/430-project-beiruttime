"""Actual received-case diagnosis, distinct from reported symptoms."""
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool, model_validator


class CaseRequestBinding(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    case_id: UUID
    request_id: UUID
    watch_id: UUID
    buyer_id: UUID
    order_id: UUID
    current: StrictBool


class Line(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: UUID
    label: str = Field(min_length=1, max_length=160, pattern=r'^\S.*')
    kind: Literal['part','labor']
    mandatory: StrictBool
    part_reference: str | None = Field(default=None, max_length=100)


class Diagnose(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    operation_id: UUID
    case_id: UUID
    request_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    assignment_revision: StrictInt = Field(ge=1)
    diagnosis: str = Field(min_length=1, max_length=2000, pattern=r'^\S.*')
    lines: list[Line] = Field(min_length=1, max_length=40)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError('duplicate_line')
        return self


class DiagnosisAuthorization(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    operation_key: str = Field(min_length=8, max_length=128)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    organization_id: UUID
    case_revision: StrictInt = Field(ge=1)
    assessment_id: UUID
    assessment_revision: StrictInt = Field(ge=1)

    @model_validator(mode='after')
    def bounded_operation_key(self):
        if not all(character.isalnum() or character in '-_' for character in self.operation_key):
            raise ValueError('invalid_operation_key')
        return self
