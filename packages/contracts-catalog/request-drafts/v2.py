"""Immutable brand request v2; v1 private drafts remain backward compatible."""

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SubmitRequest(Wire):
    draft_revision: StrictInt = Field(ge=1)
    configuration_id: UUID
    configuration_revision: StrictInt = Field(ge=1)
    movement_selection_id: UUID
    movement_revision: StrictInt = Field(ge=1)
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Selection(Wire):
    option_id: UUID
    option_revision: StrictInt = Field(ge=1)


class Correction(Wire):
    expected_revision: StrictInt = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)
    selections: dict[
        Literal["color", "material", "dial", "sophistication", "movement"], Selection
    ] = Field(min_length=5, max_length=5)


class Decision(Wire):
    expected_revision: StrictInt = Field(ge=1)
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=1000)
    assessment_id: UUID
    assessment_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    grant_id: UUID
    grant_revision: StrictInt = Field(ge=1)
