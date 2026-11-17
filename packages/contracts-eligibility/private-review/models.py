"""Versioned, purpose-specific identity review boundaries."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Binding(Strict):
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    request_id: UUID
    request_revision: int = Field(ge=1, strict=True)
    consent_revision: int = Field(ge=1, strict=True)
    quote_id: UUID
    quote_revision: int = Field(ge=1, strict=True)
    policy_revision: Literal['identity-v1'] = 'identity-v1'
    source_revision: int = Field(ge=1, strict=True)
    commitment_id: UUID
    purpose: Literal['brand-request-identity'] = 'brand-request-identity'


class Evidence(Strict):
    synthetic: Literal[True]
    identity_match: Literal['match', 'mismatch', 'unclear']
    document_valid: bool = Field(strict=True)


class Source(Strict):
    case_id: UUID
    binding: Binding
    active_identity: bool = Field(strict=True)
    active_business: bool = Field(strict=True)
    active_consent: bool = Field(strict=True)
    accepted_quote: bool = Field(strict=True)
    brand_approver_id: UUID
    eligible_reviewers: frozenset[UUID]
    evidence: Evidence | None
    active_obligation: bool = Field(strict=True)


class Command(Strict):
    schema_version: Literal['eligibility.private-review.v1'] = 'eligibility.private-review.v1'
    operation_id: UUID
    case_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    assignment_revision: int = Field(ge=1, strict=True)
    binding: Binding
    kind: Literal['claim', 'reassign', 'correct', 'decide']
    reviewer_id: UUID | None = None
    verdict: Literal['eligible', 'not_eligible'] | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator('reason')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('A reason is required / السبب مطلوب')
        return value


class Actor(Strict):
    actor_id: UUID
    organization_id: UUID | None = None
    permissions: frozenset[str]
    active: bool = Field(strict=True)


class Decision(Strict):
    operation_id: UUID
    actor_id: UUID
    reviewer_id: UUID
    assignment_revision: int
    review_revision: int
    binding: Binding
    verdict: Literal['eligible', 'not_eligible', 'correction']
    reason: str
    reviewed_at: datetime
