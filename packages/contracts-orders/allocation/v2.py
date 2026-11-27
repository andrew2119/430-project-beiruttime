"""Orders commitment v2. V1 allocation remains available during migration."""

from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt
from bt_contracts_core.models import Contract


class Commitment(Contract):
    operation_key: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    watch_id: UUID
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    expected_revision: StrictInt = Field(ge=1)
    source_id: UUID
    kind: Literal["auction_open", "first_bid", "withdraw", "edit"]
    reason: str = Field(min_length=1, max_length=200)


class Allocate(Contract):
    operation_key: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    watch_id: UUID
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    expected_revision: StrictInt = Field(ge=1)
    source_id: UUID
    kind: Literal["offer", "prebid", "winner", "brand_job"]
    buyer_id: UUID
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    currency: Literal["USD", "LBP"]
    total_minor: StrictInt = Field(ge=1, le=9000000000000000)


class EditOperationResolution(Contract):
    """Auction-only read of Catalog's exact durable physical edit outcome."""

    id: UUID
    operation_key: str = Field(min_length=1, max_length=100)
    producer: Literal["catalog"]
    kind: Literal["edit"]
    source_id: UUID
    watch_id: UUID
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    expected_revision: StrictInt = Field(ge=1)
    status: Literal["succeeded", "denied"]


class FinishEdit(Contract):
    operation_key: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    source_id: UUID
    listing_revision: StrictInt = Field(ge=1)
