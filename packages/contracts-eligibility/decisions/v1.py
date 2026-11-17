"""Versioned private eligibility commands; no evidence bytes cross this boundary."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Current(Strict):
    schema_version: Literal['eligibility-current.v1']
    subject_id: UUID
    organization_id: UUID
    watch_id: UUID
    request_id: UUID
    request_revision: int = Field(strict=True, ge=1)
    quote_id: UUID
    quote_revision: int = Field(strict=True, ge=1)
    consent_revision: int = Field(strict=True, ge=1)
    reviewer_id: UUID
    brand_approver_id: UUID
    assignment_revision: int = Field(strict=True, ge=1)
    policy_revision: Literal['objective-identity-v1']
    purpose: Literal['brand-request-identity']
    identity_current: StrictBool
    organization_current: StrictBool
    assignment_current: StrictBool
    accepted_scope_current: StrictBool
    commitment_current: StrictBool
    source_facts_current: StrictBool
    synthetic_identity_pass: StrictBool
    now: datetime
    expires_at: datetime

    @field_validator('now', 'expires_at')
    @classmethod
    def utc(cls, value):
        if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError('UTC required')
        return value


class Command(Strict):
    schema_version: Literal['eligibility-command.v1']
    operation_id: UUID
    consent_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    kind: Literal['review', 'prepare', 'consume', 'revoke']
    verdict: Literal['eligible', 'not_eligible', 'correction'] | None = None
    reason: str = Field(min_length=1, max_length=1000)
    grant_id: UUID | None = None
    use: Literal['approval', 'execution'] | None = None

    @field_validator('reason')
    @classmethod
    def explanation(cls, value):
        if not value.strip():
            raise ValueError('Reason required')
        return value


class Grant(Strict):
    grant_id: UUID
    grant_revision: int = Field(strict=True, ge=1)
    subject_id: UUID
    organization_id: UUID
    watch_id: UUID
    purpose: Literal['brand-request-identity']
    request_id: UUID
    request_revision: int = Field(strict=True, ge=1)
    quote_id: UUID
    quote_revision: int = Field(strict=True, ge=1)
    consent_revision: int = Field(strict=True, ge=1)
    reviewer_id: UUID
    brand_approver_id: UUID
    assignment_revision: int = Field(strict=True, ge=1)
    policy_revision: Literal['objective-identity-v1']
    review_revision: int = Field(strict=True, ge=1)
    use: Literal['approval', 'execution']
    expires_at: datetime
    revoked_at: datetime | None
    consumed_at: datetime | None


class Result(Strict):
    schema_version: Literal['eligibility-result.v1']
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID | None
    actor_id: UUID
    organization_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    state: Literal['pending', 'stale', 'denied', 'eligible', 'not_eligible', 'correction', 'prepared', 'consumed', 'revoked']
    revision: int = Field(strict=True, ge=0)
    pending_reason: str | None
    next_actor: str | None
    next_review_at: datetime | None
    reason_code: str | None = None
    grant: Grant | None = None
