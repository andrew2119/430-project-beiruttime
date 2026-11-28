"""Saved searches v1. Personal criteria and receipts never enter public events."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, ValidationError, field_validator, model_validator
from bt_contracts_core.models import Contract
from bt_contracts_core.errors import PublicError

MAX_MINOR = 9_000_000_000_000_000


class Criteria(Contract):
    q: str = Field(default='', max_length=160)
    brand: str = Field(default='', max_length=100)
    model: str = Field(default='', max_length=160)
    location: str = Field(default='', max_length=160)
    min_minor: StrictInt | None = Field(default=None, ge=0, le=MAX_MINOR)
    max_minor: StrictInt | None = Field(default=None, ge=0, le=MAX_MINOR)
    currency: Literal['USD'] = 'USD'
    sale_mode: Literal['', 'fixed', 'auction', 'offer'] = ''
    sort: Literal['newest', 'price_asc', 'price_desc', 'ending_soon'] = 'newest'

    @model_validator(mode='wrap')
    @classmethod
    def filter_errors(cls, value, handler):
        try:
            return handler(value)
        except ValidationError:
            raise PublicError('invalid_filters', 'Check the search filters.', status=422) from None

    @field_validator('min_minor', 'max_minor', mode='before')
    @classmethod
    def integer_range(cls, value):
        if value is not None and (type(value) is not int or not 0 <= value <= MAX_MINOR):
            raise PublicError('invalid_range', 'Enter integer minor units.', status=422)
        return value

    @model_validator(mode='after')
    def valid(self):
        if len(self.q.split()) > 8:
            raise PublicError('invalid_filters', 'Check the search filters.', status=422)
        if self.min_minor is not None and self.max_minor is not None and self.min_minor > self.max_minor:
            raise PublicError('invalid_range', 'Check the search range.', status=422)
        return self


class Command(Contract):
    schema_version: Literal['saved-searches.v1'] = 'saved-searches.v1'
    operation_id: UUID
    subject_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    kind: Literal['save', 'remove'] = 'save'
    name: str = Field(min_length=1, max_length=120)
    criteria: Criteria
    alerts_enabled: bool

    @model_validator(mode='after')
    def named(self):
        if not self.name.strip() or any(ord(c) < 32 for c in self.name):
            raise ValueError('invalid_name')
        return self


class Publication(Contract):
    occurrence_id: UUID
    listing_id: UUID
    watch_id: UUID
    revision: StrictInt = Field(ge=1)
    published_at: AwareDatetime
    sample: bool = False


class Validation(Contract):
    criteria: Criteria
    semantics_revision: str = Field(min_length=1, max_length=100)


class Match(Contract):
    occurrence_id: UUID
    listing_id: UUID
    watch_id: UUID
    revision: StrictInt = Field(ge=1)
    semantics_revision: str = Field(min_length=1, max_length=100)
    matches: bool
    currently_public: bool
