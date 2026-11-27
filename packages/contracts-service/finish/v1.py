"""Exact assessed finish consent; no execution or payment authority."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, AwareDatetime, model_validator

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

class Area(Contract):
    area_id: UUID
    name_en: str = Field(min_length=1, max_length=160)
    name_ar: str = Field(min_length=1, max_length=160)
    original: Literal['brushed', 'mirror', 'mixed', 'unknown']
    desired: Literal['brushed', 'mirror', 'preserve']
    material_known: StrictBool
    preservation_assessed: StrictBool
    material_en: str = Field(min_length=1, max_length=300)
    material_ar: str = Field(min_length=1, max_length=300)
    coating: Literal['absent', 'present', 'unknown']
    plating: Literal['absent', 'thin', 'present', 'unknown']
    engraving: Literal['absent', 'present', 'unknown']
    preservation_en: str = Field(min_length=1, max_length=1000)
    preservation_ar: str = Field(min_length=1, max_length=1000)
    assessed_action: Literal['polish', 'brush', 'no_polish']
    suitable: StrictBool

class Choice(Contract):
    area_id: UUID
    decision: Literal['consent', 'no_polish']

class Command(Contract):
    schema_version: Literal['finish.v1']
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    source_revision: StrictInt = Field(ge=1)
    assessment_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    choices: tuple[Choice, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def unique_areas(self):
        if len({x.area_id for x in self.choices}) != len(self.choices):
            raise ValueError('Duplicate area')
        return self

class Terms(Contract):
    revision: StrictInt = Field(ge=1)
    fee_en: str = Field(min_length=1, max_length=2000)
    fee_ar: str = Field(min_length=1, max_length=2000)
    return_en: str = Field(min_length=1, max_length=2000)
    return_ar: str = Field(min_length=1, max_length=2000)
    assurance_en: str = Field(min_length=1, max_length=2000)
    assurance_ar: str = Field(min_length=1, max_length=2000)
    support_path: Literal['/inbox']

class Snapshot(Contract):
    subject_id: UUID
    watch_id: UUID
    buyer_id: UUID
    organization_id: UUID
    source_revision: StrictInt = Field(ge=1)
    assessment_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    terms: Terms
    commitment_id: UUID
    current: StrictBool
    assigned: StrictBool
    retained: StrictBool
    currency: Literal['USD']
    total_minor: StrictInt = Field(ge=0, le=999999999999)
    valid_until: AwareDatetime
    areas: tuple[Area, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def unique_areas(self):
        if len({x.area_id for x in self.areas}) != len(self.areas):
            raise ValueError('Duplicate area')
        return self

class Result(Contract):
    schema_version: Literal['finish.v1']
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    state: Literal['recorded', 'pending']
    revision: StrictInt = Field(ge=0)
    pending_reason: Literal['source_unavailable'] | None
    next_actor: Literal['buyer'] | None
    next_review_at: AwareDatetime | None

    @model_validator(mode='after')
    def coherent_state(self):
        if self.state == 'recorded':
            if self.revision != self.expected_revision + 1 or self.pending_reason is not None or self.next_actor is not None:
                raise ValueError('Invalid recorded result')
        elif self.revision != self.expected_revision or self.pending_reason != 'source_unavailable' or self.next_actor != 'buyer':
            raise ValueError('Invalid pending result')
        if self.next_review_at is not None:
            raise ValueError('No review appointment is scheduled by consent')
        return self

class Detail(Contract):
    source: Snapshot
    revision: StrictInt = Field(ge=0)
    choices: tuple[Choice, ...] = Field(max_length=32)
