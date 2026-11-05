"""Exact assessed scope and explicit buyer decisions shared by brand/repair quotes."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, StrictBool, model_validator
from bt_contracts_core.models import Contract

MAX_MINOR = 9_000_000_000_000


class AssessedScopeLine(Contract):
    id: UUID
    label: str = Field(min_length=1, max_length=160)
    kind: Literal['part', 'labor']
    mandatory: StrictBool
    part_reference: str | None = Field(default=None, max_length=100)


class AssessedLine(AssessedScopeLine):
    amount_minor: StrictInt = Field(ge=0, le=MAX_MINOR)


class IssueQuote(Contract):
    source_id: UUID
    source_revision: StrictInt = Field(ge=1)
    assessment_id: UUID
    assessment_revision: StrictInt = Field(ge=1)
    currency: Literal['USD', 'LBP']
    lines: list[AssessedLine] = Field(min_length=1, max_length=40)
    assessment_fee_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    return_fee_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    warranty_terms: str = Field(min_length=1, max_length=2000)
    modification_terms: str = Field(min_length=1, max_length=2000)
    indicative_min_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    indicative_max_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    indicative_basis: str = Field(min_length=1, max_length=1000)
    lead_time_days: StrictInt = Field(ge=0, le=730)
    expires_at: AwareDatetime
    schedule_id: Literal['sample-v1']

    @model_validator(mode='after')
    def valid_scope(self):
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError('Duplicate line')
        if sum(line.amount_minor for line in self.lines) + self.assessment_fee_minor > MAX_MINOR:
            raise ValueError('Quote exceeds supported range')
        if self.indicative_max_minor < self.indicative_min_minor:
            raise ValueError('Invalid indicative range')
        return self


class AcceptQuote(Contract):
    quote_revision: StrictInt = Field(ge=1)
    selected_line_ids: list[UUID] = Field(min_length=1, max_length=40)
    payable_minor: StrictInt = Field(gt=0, le=MAX_MINOR * 2)
    terms_digest: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def unique_lines(self):
        if len(set(self.selected_line_ids)) != len(self.selected_line_ids):
            raise ValueError('Duplicate selection')
        return self


class DeclineQuote(Contract):
    quote_revision: StrictInt = Field(ge=1)
    terms_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
