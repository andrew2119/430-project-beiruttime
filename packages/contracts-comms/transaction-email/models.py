"""Private synthetic delivery contract, version 1."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt, AwareDatetime, model_validator


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal['transaction-email.v1'] = 'transaction-email.v1'
    operation_id: UUID
    event_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    subject_id: UUID
    watch_id: UUID
    expected_revision: StrictInt = Field(ge=1)
    recipient_revision: StrictInt = Field(ge=1)
    quote_id: UUID | None
    quote_revision: StrictInt | None = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    kind: Literal['confirmation', 'quote', 'ready', 'refund', 'receipt-link']
    locale: Literal['en', 'ar']

    @model_validator(mode='after')
    def paired_quote(self):
        if (self.quote_id is None) != (self.quote_revision is None):
            raise ValueError('Quote binding must be complete')
        return self


class Authority(BaseModel):
    """A fresh producer result; never derived from a projection or request body."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    actor_id: UUID
    organization_id: UUID | None
    subject_id: UUID
    watch_id: UUID
    event_id: UUID
    revision: StrictInt = Field(ge=1)
    recipient_revision: StrictInt = Field(ge=1)
    verified_revision: StrictInt | None = Field(ge=1)
    quote_id: UUID | None
    quote_revision: StrictInt | None = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    kind: Literal['confirmation', 'quote', 'ready', 'refund', 'receipt-link']
    support_actor_id: UUID
    permitted: bool
    occurred_at: AwareDatetime
    valid_until: AwareDatetime
    destination: Literal['checkout', 'prices', 'inbox']
    destination_id: UUID


class Result(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['transaction-email.v1'] = 'transaction-email.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: int
    revision: int
    state: Literal['captured', 'recorded', 'failed', 'possibly_sent']
    attempt_id: UUID | None
    locale: Literal['en', 'ar']
    kind: Literal['confirmation', 'quote', 'ready', 'refund', 'receipt-link']
    synthetic: Literal[True] = True
    pending_reason: str | None
    next_actor: UUID
    next_review_at: datetime | None
    available_at: datetime
    authenticated_link: str


class ReadScope(BaseModel):
    """Fresh current read scope for counts, including pages with no rows."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    actor_id: UUID
    organization_id: UUID | None
    permitted: bool
    subject_ids: frozenset[UUID] = Field(max_length=10000)
