from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Validate(Wire):
    configuration_revision: StrictInt = Field(ge=1)
    movement_selection_id: UUID
    movement_revision: StrictInt = Field(ge=1)


class Mounting(Wire):
    case: str = Field(min_length=1, max_length=80)
    dial: str = Field(min_length=1, max_length=80)
    hands: str = Field(min_length=1, max_length=80)
    functions: list[str] = Field(max_length=20)


class Rule(Wire):
    expected_revision: StrictInt = Field(ge=0)
    base_model: str = Field(min_length=1, max_length=80)
    caliber: str = Field(min_length=1, max_length=80)
    option_ids: list[UUID] = Field(min_length=5, max_length=5)
    option_revisions: dict[UUID, StrictInt] = Field(min_length=5, max_length=5)
    mounting: Mounting
    status: Literal["valid", "incompatible", "parts_unavailable", "manual_assessment"]
    reason: str = Field(min_length=3, max_length=1000)


    @model_validator(mode="after")
    def exact_option_versions(self):
        if len(set(self.option_ids)) != 5 or set(self.option_ids) != set(self.option_revisions):
            raise ValueError("Five distinct options and their exact revisions are required")
        if any(revision < 1 for revision in self.option_revisions.values()):
            raise ValueError("Option revisions must be positive")
        if len(set(self.mounting.functions)) != len(self.mounting.functions):
            raise ValueError("Movement functions must be distinct")
        return self
