"""Private current-operation contract, version one."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['seller-follows.v1']
    operation_id: UUID
    actor_id: UUID
    organization_id: None = None
    seller_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    following: bool = Field(strict=True)
    alerts_enabled: bool = Field(strict=True)


class Publication(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['catalog.publication.v1']
    event_id: UUID
    seller_id: UUID
    watch_id: UUID
    revision: int = Field(strict=True, ge=1)
    published_at: AwareDatetime
    sample: bool = Field(strict=True)

    @field_validator('published_at')
    @classmethod
    def utc(cls, value: datetime):
        return value.astimezone(timezone.utc)


class NoticeCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['seller-follows.v1']
    operation_id: UUID
    actor_id: UUID
    organization_id: None = None
    notice_id: UUID
    expected_revision: int = Field(strict=True, ge=1)
    action: Literal['read', 'clear']
