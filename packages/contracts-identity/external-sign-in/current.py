"""External sign-in v1; private commands never enter public events."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Callback(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1] = 1
    operation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,100}$')
    expected_revision: int = Field(ge=0, le=2147483647)
    state: str = Field(min_length=32, max_length=128)
    code: str = Field(min_length=1, max_length=2048)


class CurrentOperation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1] = 1
    operation_id: str
    subject_id: str | None = None
    watch_id: None = None
    actor_id: str | None = None
    organization_id: str | None = None
    expected_revision: int = Field(ge=0, le=2147483647)
    state: Literal['ready', 'pending', 'signed_in', 'linked', 'denied', 'stale', 'unavailable']
    revision: int = Field(ge=0, le=2147483647)
    pending_reason: Literal['identity_unavailable'] | None = None
    next_actor: Literal['buyer', 'identity'] = 'buyer'
    next_review_at: None = None
