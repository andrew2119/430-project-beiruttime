"""Versioned history boundary. Private source fields never cross this boundary."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Warranty(Model):
    issuer_id: UUID
    scope_code: Literal['accepted_work', 'installed_parts']
    starts_at: datetime
    terms_revision: int = Field(ge=1)
    terms_en: str = Field(min_length=1, max_length=4000)
    terms_ar: str = Field(min_length=1, max_length=4000)

    @field_validator('starts_at')
    @classmethod
    def utc(cls, value):
        if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError('UTC required')
        return value


class Entry(Model):
    job_id: UUID
    watch_id: UUID
    organization_id: UUID
    kind: Literal['service', 'modification']
    work_codes: tuple[Literal['maintenance', 'repair', 'cleaning', 'polishing', 'bracelet_fit', 'customization'], ...]
    released_at: datetime
    source_revision: int = Field(ge=1)
    warranty: Warranty | None

    @field_validator('released_at')
    @classmethod
    def utc(cls, value):
        return Warranty.utc(value)


class Result(Model):
    schema_version: Literal['history.v1'] = 'history.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: int = Field(ge=0)
    state: Literal['ready', 'pending', 'denied', 'stale', 'unavailable']
    revision: int = Field(ge=0)
    pending_reason: Literal['source_pending', 'source_unavailable'] | None = None
    next_actor: Literal['reader', 'record_operator']
    next_review_at: datetime | None = None
    items: tuple[Entry, ...] = ()
    total: int = Field(ge=0)
    page: int = Field(ge=0)
    page_size: int = Field(ge=1, le=50)


class PublicationResult(Result):
    state: Literal['ready', 'pending', 'denied', 'stale']
    schema_version: Literal['history-publication.v1'] = 'history-publication.v1'


class PublicationBody(Model):
    operation_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    job_ids: tuple[UUID, ...] = Field(max_length=50)
