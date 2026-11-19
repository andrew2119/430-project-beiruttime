"""Versioned enlargement commands. No execution or financial authority is implied."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["enlargement.v1"] = "enlargement.v1"
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    request_id: str = Field(max_length=36)
    watch_id: str = Field(max_length=36)
    organization_id: str = Field(max_length=36)
    expected_revision: int = Field(ge=0, le=2147483647)
    source_revision: int = Field(ge=1)
    kind: Literal["request", "assess", "accept", "work", "fit"]
    payload: dict

    @field_validator("request_id", "watch_id", "organization_id")
    @classmethod
    def identifier(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("invalid_identifier")
        return value

OPERATIONS = {
    "request": {"permission": "buyer", "from": [None], "to": "requested"},
    "assess": {"permission": "assessor", "from": ["requested", "waiting", "assessed", "accepted", "worked", "rework"], "to": "assessed"},
    "accept": {"permission": "buyer", "from": ["assessed"], "to": "accepted"},
    "work": {"permission": "staff", "from": ["accepted", "waiting", "rework"], "to": "worked"},
    "fit": {"permission": "quality", "from": ["worked"], "to": "fit_recorded"},
}
