"""Counteroffer v1 private command and retained economics."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt, AwareDatetime

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

class Economics(Contract):
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    currency: Literal['USD']
    price_minor: StrictInt = Field(gt=0, le=9_000_000_000_000)
    buyer_fee_minor: StrictInt = Field(ge=0)
    seller_commission_minor: StrictInt = Field(ge=0)
    total_minor: StrictInt = Field(gt=0)
    terms_revision: StrictInt = Field(ge=1)

class Command(Contract):
    schema_version: Literal['counteroffers.v1'] = 'counteroffers.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt = Field(ge=1)
    source_revision: StrictInt = Field(ge=1)
    authority_revision: StrictInt = Field(ge=1)
    kind: Literal['propose', 'accept', 'reject']
    economics: Economics
    reviewed_revision: StrictInt | None = Field(default=None, ge=1)

class Offer(Contract):
    id: UUID
    watch_id: UUID
    subject_id: UUID
    seller_id: UUID
    buyer_id: UUID
    organization_id: UUID | None
    revision: StrictInt = Field(ge=1)
    state: Literal['sent', 'superseded', 'rejected', 'closed', 'accepted']
    economics: Economics
    sent_at: AwareDatetime
    expires_at: AwareDatetime
    predecessor_id: UUID | None = None

class Authority(Contract):
    actor_id: UUID
    organization_id: UUID | None
    permitted: bool
    seller_approved: bool
    scope_revision: StrictInt = Field(ge=1)

class Facts(Contract):
    watch_id: UUID
    subject_id: UUID
    source_revision: StrictInt = Field(ge=1)
    mode: Literal['fixed', 'offers_only', 'auction']
    available: bool
    blocked: bool
    quote_current: bool
    economics: Economics

class Result(Contract):
    schema_version: Literal['counteroffers.v1'] = 'counteroffers.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt = Field(ge=1)
    state: Literal['succeeded', 'denied', 'pending', 'unavailable']
    code: str
    revision: StrictInt = Field(ge=1)
    current: Offer | None = None
    next_actor: Literal['buyer', 'seller', 'support']
    pending_reason: str | None = None
    next_review_at: datetime | None = None
    order_id: UUID | None = None
