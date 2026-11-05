"""Auction listing-edit fence v2. Catalog retains the user authorization/intent."""
from uuid import UUID
from typing import Literal
from pydantic import Field, StrictInt, model_validator
from bt_contracts_core.models import Contract


class PrepareListingEdit(Contract):
    operation_id: UUID
    listing_id: UUID
    watch_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    next_revision: StrictInt = Field(ge=2)
    facts_digest: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def consecutive(self):
        if self.next_revision != self.listing_revision + 1:
            raise ValueError('The next listing revision must be consecutive')
        return self


class CommitListingEdit(Contract):
    listing_revision: StrictInt = Field(ge=2)


class PrepareListingEditV3(PrepareListingEdit):
    orders_operation_key: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')
    orders_expected_revision: StrictInt = Field(ge=1)
    lease_seconds: StrictInt = Field(default=120, ge=30, le=300)


class EditOperationResolution(Contract):
    """orders-commitment/v2.1 read; never accept caller-supplied proof."""
    id: UUID
    operation_key: str = Field(min_length=1, max_length=100)
    producer: Literal['catalog']
    kind: Literal['edit']
    source_id: UUID
    watch_id: UUID
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    expected_revision: StrictInt = Field(ge=1)
    status: Literal['succeeded', 'denied']
