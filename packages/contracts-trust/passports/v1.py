"""Inspection summary v1. Public fields are an explicit closed allowlist."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)


class Issue(Closed):
    schema_version: Literal['passports.issue.v1'] = 'passports.issue.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    expected_revision: int = Field(ge=1, le=2147483647)
    inspection_id: UUID


class Summary(Closed):
    schema_version: Literal['passports.summary.v1'] = 'passports.summary.v1'
    passport_id: UUID
    issuer_id: UUID
    inspected_at: datetime
    issued_at: datetime
    scope: Literal['independent_private_sale_inspection']
    watch_reference: UUID
    inspected_revision: int = Field(ge=1, le=2147483647)
    claim: Literal['historical_inspection_summary_only']

    @field_validator('inspected_at', 'issued_at')
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError('UTC required')
        return value


class Signed(Closed):
    summary: Summary
    key_id: UUID
    signature: str = Field(pattern=r'^[A-Za-z0-9_-]{86}$')
