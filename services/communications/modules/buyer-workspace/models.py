"""Bounded owner-private input contracts; no cap field is ever projected here."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Band(Record):
    from_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    step_minor: int = Field(strict=True, ge=1, le=9_000_000_000_000_000)


class Bid(Record):
    """Exact Auction own-bids v1; my_status is NOT the Auction lifecycle."""
    id: UUID
    auction_id: UUID
    listing_id: UUID
    buyer_id: UUID
    currency: Literal['USD', 'LBP']
    opening_minor: int = Field(strict=True, ge=1, le=9_000_000_000_000_000)
    current_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    current_price_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    next_minimum_minor: int = Field(strict=True, ge=1, le=9_000_000_000_000_000)
    increment_bands: list[Band] = Field(min_length=1, max_length=20)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    server_time: AwareDatetime
    revision: int = Field(strict=True, ge=1)
    accepted_sequence: int = Field(strict=True, ge=0)
    rules_version: str = Field(min_length=1, max_length=80)
    extension_policy: str = Field(min_length=1, max_length=80)
    high_value_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    reserve_set: bool = Field(strict=True)
    leader: str | None = Field(max_length=100)
    status: Literal['live', 'scheduled', 'ended']
    my_status: Literal['leading', 'outbid']
    next_action: Literal['review_bid', 'auction_ended']

    @model_validator(mode='after')
    def consistent(self):
        if self.id != self.auction_id or self.current_minor != self.current_price_minor:
            raise ValueError('Inconsistent auction projection')
        if (self.status == 'ended') != (self.next_action == 'auction_ended'):
            raise ValueError('Inconsistent auction action')
        return self


class Bids(Record):
    items: list[Bid] = Field(max_length=100)
    next_cursor: UUID | None = None


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
