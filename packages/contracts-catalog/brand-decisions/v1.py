"""Closed public event payloads, never private request/evidence projections."""

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class RequestEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    brand_id: UUID


class DecisionEvent(RequestEvent):
    decision_id: UUID
    status: Literal["approved", "rejected"]
