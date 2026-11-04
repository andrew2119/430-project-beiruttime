"""Bounded owner-private input contracts; no cap field is ever projected here."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Bid(Record):
    auction_id: UUID
    listing_id: UUID
    buyer_id: UUID
    status: Literal['leading', 'outbid']
    current_price_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    currency: Literal['USD', 'LBP']
    revision: int = Field(strict=True, ge=1)
    ends_at: AwareDatetime
    is_demo: bool = False


class Bids(Record):
    items: list[Bid] = Field(max_length=100)
    next_cursor: str | None = Field(default=None, max_length=200)


class Reservation(Record):
    """Frozen Orders allocation v1 buyer-only reservation projection."""
    reservation_id: UUID
    listing_id: UUID
    buyer_id: UUID
    state: Literal['awaiting_payment']
    total_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    currency: Literal['USD', 'LBP']
    revision: int = Field(strict=True, ge=1)
    expires_at: AwareDatetime
    is_demo: bool = Field(strict=True)


class Reservations(Record):
    items: list[Reservation] = Field(max_length=100)
    next_cursor: UUID | None = None
