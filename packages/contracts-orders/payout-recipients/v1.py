"""Private synthetic recipient commands. No account numbers or credentials."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt

class Change(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal[1] = 1
    operation_id: UUID
    subject_id: UUID
    organization_id: UUID | None = None
    expected_revision: StrictInt = Field(ge=0)
    method: Literal['bank', 'whish', 'omt']
    reference: str = Field(pattern=r'^synthetic_[a-zA-Z0-9_-]{1,64}$')
    proof_id: UUID

class Result(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    operation_id: UUID | None = None
    subject_id: UUID
    organization_id: UUID | None = None
    watch_id: UUID | None
    actor_id: str
    expected_revision: StrictInt | None = Field(ge=0)
    next_actor: str | None
    next_review_at: datetime | None
    state: Literal['succeeded', 'denied', 'pending']
    revision: StrictInt = Field(ge=0)
    recipient_version: StrictInt | None = Field(default=None, ge=1)
    code: str | None = None
    pending_reason: str | None
    method: Literal['bank', 'whish', 'omt'] | None = None
    reference: str | None = None
    synthetic: bool = True
