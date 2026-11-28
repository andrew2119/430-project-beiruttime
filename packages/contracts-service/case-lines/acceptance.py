"""Transport of an acknowledged quote selection; never independent work consent."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Acceptance(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    operation_id: UUID
    case_id: UUID
    request_id: UUID
    request_revision: StrictInt | None = Field(default=None, ge=1)
    actor_id: UUID
    organization_id: UUID
    watch_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    assessment_id: UUID
    assessment_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
