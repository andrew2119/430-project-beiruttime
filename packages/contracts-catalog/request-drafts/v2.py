"""Immutable brand request v2; v1 private drafts remain backward compatible."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SubmitRequest(Wire):
    draft_revision: StrictInt = Field(ge=1, le=2147483647)
    configuration_id: UUID
    configuration_revision: StrictInt = Field(ge=1, le=2147483647)
    movement_selection_id: UUID
    movement_revision: StrictInt = Field(ge=1, le=2147483647)
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Selection(Wire):
    option_id: UUID
    option_revision: StrictInt = Field(ge=1, le=2147483647)


class Correction(Wire):
    expected_revision: StrictInt = Field(ge=1, le=2147483647)
    reason: str = Field(min_length=3, max_length=1000)
    selections: dict[
        Literal["color", "material", "dial", "sophistication", "movement"], Selection
    ] = Field(min_length=5, max_length=5)


class Decision(Wire):
    expected_revision: StrictInt = Field(ge=1, le=2147483647)
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=1000)
    assessment_id: UUID
    assessment_revision: StrictInt = Field(ge=1, le=2147483647)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1, le=2147483647)
    grant_id: UUID
    grant_revision: StrictInt = Field(ge=1, le=2147483647)


class OptionSnapshot(Selection):
    definition: dict


class RequestSnapshot(Wire):
    brand_id: UUID
    base_model: str = Field(min_length=1, max_length=80)
    caliber: str = Field(min_length=1, max_length=80)
    selections: dict[
        Literal["color", "material", "dial", "sophistication", "movement"], OptionSnapshot
    ] = Field(min_length=5, max_length=5)
    reference_ids: list[UUID] = Field(max_length=3)
    movement_mounting: dict
    compatibility_rule: dict | None
    compatibility_status: Literal["valid", "manual_assessment"]


class SubmittedRequest(Wire):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    id: UUID
    revision: StrictInt = Field(ge=1, le=2147483647)
    draft_id: UUID
    buyer_id: UUID
    brand_id: UUID
    status: Literal["submitted"]
    configuration_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    configuration: RequestSnapshot
    watch_context: Literal["owned_watch", "seller_base"]
    watch_reference: str = Field(min_length=1, max_length=300)
    scope_intent: str = Field(max_length=1000)
    notes: str = Field(max_length=4000)
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def utc_instant(cls, value):
        if value.utcoffset().total_seconds() != 0:
            raise ValueError("A UTC instant is required")
        return value

    @model_validator(mode="after")
    def matching_brand(self):
        if self.brand_id != self.configuration.brand_id:
            raise ValueError("Snapshot belongs to another brand")
        return self


class SubmissionOperation(Wire):
    id: UUID
    status: Literal["succeeded"]
    resource_id: UUID
    request: SubmittedRequest


    @model_validator(mode="after")
    def matching_request(self):
        if self.resource_id != self.request.id:
            raise ValueError("Operation belongs to another request")
        return self
