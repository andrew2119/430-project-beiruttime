"""Closed, public-only similar watch read contract, version one."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

MAX_MINOR = 1_000_000_000_000


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Query(Model):
    operation_id: UUID
    subject_id: UUID
    expected_revision: StrictInt = Field(ge=1)
    offset: StrictInt = Field(default=0, ge=0, le=1000, multiple_of=20)


class Watch(Model):
    id: UUID
    watch_id: UUID
    revision: StrictInt = Field(ge=1)
    title: str = Field(min_length=1, max_length=320)
    brand: str = Field(min_length=1, max_length=100)
    reference: str = Field(max_length=100)
    currency: Literal['USD'] = 'USD'
    price_minor: StrictInt | None = Field(default=None, ge=1, le=MAX_MINOR)
    available: StrictBool
    sample: StrictBool


class Match(Model):
    watch: Watch
    rule: Literal['reference', 'brand', 'price_band']


class Result(Model):
    schema_version: Literal['similar-watches.v1'] = 'similar-watches.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID | None = None
    actor_id: None = None
    organization_id: None = None
    expected_revision: StrictInt
    state: Literal['ready', 'empty', 'stale', 'denied', 'unavailable']
    revision: StrictInt | None = None
    pending_reason: Literal['current_source_unavailable'] | None = None
    next_actor: Literal['viewer'] = 'viewer'
    next_review_at: None = None
    rules_version: Literal['reference-brand-band.v1'] = 'reference-brand-band.v1'
    items: tuple[Match, ...] = Field(default=(), max_length=20)
    total: StrictInt = Field(default=0, ge=0, le=1000)
    offset: StrictInt = Field(ge=0, le=1000)
    next_offset: StrictInt | None = None
