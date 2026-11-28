from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal['brand-assessment.v1']
    operation_id: str = Field(min_length=8, max_length=100)
    subject_id: str = Field(min_length=1, max_length=100)
    watch_id: str = Field(min_length=1, max_length=100)
    actor_id: str = Field(min_length=1, max_length=100)
    organization_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0)
    request_revision: int = Field(ge=1)
    assignment_revision: int = Field(ge=0)
    capability_revision: int = Field(ge=1)
    kind: Literal['claim', 'release', 'reassign', 'assess', 'correct']
    replacement_id: str | None = Field(default=None, max_length=100)
    feasibility: Literal['feasible', 'incompatible', 'parts_unavailable', 'manual'] | None = None
    parts: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=50)
    limitations: str = Field(default='', max_length=4000)
    lead_time_basis: str = Field(default='', max_length=2000)
    reason: str = Field(default='', max_length=2000)
