"""Versioned private business command contracts. Evidence stays private."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["identity.business.v2"] = "identity.business.v2"
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID | None = None
    actor_id: UUID
    organization_id: UUID | None = None
    expected_revision: int = Field(ge=0)


class PossessionCommand(Envelope):
    kind: Literal["issue", "submit", "assign", "decide"]
    watch_id: UUID
    watch_revision: int = Field(ge=1)
    listing_revision: int = Field(ge=1)
    reviewer_id: UUID | None = None
    challenge_id: UUID | None = None
    assignment_revision: int | None = Field(default=None, ge=1)
    code: str | None = Field(default=None, min_length=6, max_length=6)
    evidence_ref: UUID | None = None
    verdict: Literal["approved", "correction", "rejected", "suspended"] | None = None
    reason: str | None = Field(default=None, min_length=5, max_length=500)

    @model_validator(mode="after")
    def required_operation_fields(self):
        if self.kind == "submit" and (self.challenge_id is None or self.code is None or self.evidence_ref is None):
            raise ValueError("Private proof required / إثبات خاص مطلوب")
        if self.kind == "assign" and (self.reviewer_id is None or self.reason is None):
            raise ValueError("Reasoned assignment required / تعيين مسبب مطلوب")
        if self.kind == "decide" and (self.verdict is None or self.reason is None or self.assignment_revision is None):
            raise ValueError("Current reasoned decision required / قرار حالي مسبب مطلوب")
        if self.organization_id is not None:
            raise ValueError("Personal listing required / إعلان شخصي مطلوب")
        return self

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if value is not None and len(value.strip()) < 5:
            raise ValueError("A reason is required / السبب مطلوب")
        return value.strip() if value is not None else None

    @field_validator("code")
    @classmethod
    def digits(cls, value):
        if value is None:
            return None
        if not all(character.isdecimal() for character in value):
            raise ValueError("Six digits required / ستة أرقام مطلوبة")
        return "".join(str(int(character)) for character in value)


class StaffCommand(Envelope):
    kind: Literal["grant", "suspend", "remove"]
    organization_id: UUID
    permissions: tuple[str, ...] = ()
    ceiling_revision: int = Field(ge=1)
    job_revisions: dict[UUID, int] = Field(default_factory=dict)
    replacement_revision: int | None = Field(default=None, ge=1)
    replacement_id: UUID | None = None
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("A reason is required / السبب مطلوب")
        return value.strip()


class Result(Envelope):
    operation_state: Literal["pending", "committed"]
    state: str
    revision: int = Field(ge=1)
    pending_reason: str | None = None
    next_actor: UUID | None = None
    next_review_at: datetime | None = None


OPERATIONS = {
    "business.directory.v2": "GET /v2/businesses",
    "business.records.v2": "GET /v2/businesses/manage/records",
    "business.memberships.v2": "GET /v2/businesses/{business_id}/memberships",
    "review.queue.v2": "GET /v2/private-reviews",
    "review.mine.v2": "GET /v2/private-reviews/mine",
    "review.history.v2": "GET /v2/private-reviews/{review_id}",
    "possession.listing.v2": "GET /v2/listing-possession/listings/{watch_id}",
    "possession.history.v2": "GET /v2/listing-possession/history/{watch_id}",
    "possession.photo.v2": "POST /v2/listing-possession/photos",
    "possession.evidence.v2": "GET /v2/listing-possession/evidence/{watch_id}",
    "business.workspace.v2": "GET /v2/business-staff/workspaces/{business_id}",
    "possession.issue.v2": "POST /v2/listing-possession/challenges",
    "possession.submit.v2": "POST /v2/listing-possession/submissions",
    "possession.assign.v2": "POST /v2/listing-possession/assignments",
    "possession.decide.v2": "POST /v2/listing-possession/decisions",
    "business.staff.v2": "POST /v2/business-staff/commands",
    "business.operation.v2": "GET /v2/business-operations/{operation_id}",
}
