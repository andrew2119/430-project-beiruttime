"""Private publication eligibility response v1."""
from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator


class PublicationEligibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["listing-eligibility.v1"]
    operation_id: str = Field(min_length=1, max_length=128)
    subject_id: UUID
    listing_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt = Field(ge=1)
    identity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["eligible", "denied", "pending"]
    revision: StrictInt = Field(ge=1)
    pending_reason: str | None = Field(max_length=128)
    next_actor: str | None = Field(max_length=128)
    next_review_at: AwareDatetime | None
    current: StrictBool
    duplicate_review: Literal["clear", "required", "denied"]
    proof_listing_id: UUID | None = None
    proof_watch_id: UUID | None = None
    proof_identity_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proof_revision: StrictInt | None = Field(default=None, ge=1)
    code_issued_at: AwareDatetime | None = None
    proof_submitted_at: AwareDatetime | None = None
    single_use_code_consumed: StrictBool = False
    reviewed: StrictBool = False

    @model_validator(mode="after")
    def private_proof(self):
        if self.subject_id != self.listing_id:
            raise ValueError("Eligibility subject must be the listing")
        if self.state == "pending" and (
            not self.pending_reason or not self.pending_reason.strip()
            or not self.next_actor or not self.next_actor.strip()
            or self.next_review_at is None
        ):
            raise ValueError("Pending review requires a reason, responsible role and review time")
        if self.state == "eligible" and self.organization_id is None:
            if (
                self.proof_listing_id != self.listing_id
                or self.proof_watch_id != self.watch_id
                or self.proof_identity_digest != self.identity_digest
                or self.proof_revision is None
                or not self.reviewed
                or not self.single_use_code_consumed
                or self.code_issued_at is None
                or self.proof_submitted_at is None
                or not self.code_issued_at <= self.proof_submitted_at < self.code_issued_at + timedelta(hours=24)
            ):
                raise ValueError("Current listing-specific reviewed possession is required")
        return self
