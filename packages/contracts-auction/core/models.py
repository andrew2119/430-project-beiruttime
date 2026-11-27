from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, model_validator
from bt_contracts_core.models import Contract

MAX_MINOR = 9_000_000_000_000


class Band(Contract):
    from_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    step_minor: StrictInt = Field(ge=1, le=MAX_MINOR)


class AuctionRules(Contract):
    currency: Literal['USD']
    opening_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    increment_bands: list[Band] = Field(min_length=1, max_length=20)
    reserve_minor: StrictInt | None = Field(default=None, ge=1, le=MAX_MINOR)
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode='after')
    def consistent(self):
        thresholds = [band.from_minor for band in self.increment_bands]
        if thresholds[0] != 0 or thresholds != sorted(set(thresholds)):
            raise ValueError('Bands must start at zero and ascend uniquely')
        if self.ends_at <= self.starts_at or (self.ends_at - self.starts_at).total_seconds() > 90 * 86400:
            raise ValueError('Auction duration must be positive and at most ninety days')
        opening_step = next(band.step_minor for band in reversed(self.increment_bands)
            if self.opening_minor >= band.from_minor)
        if self.opening_minor + opening_step > MAX_MINOR:
            raise ValueError('Opening and next increment must fit the supported monetary range')
        if self.reserve_minor is not None and self.reserve_minor < self.opening_minor:
            raise ValueError('Reserve cannot be below opening price')
        return self


class CreateAuction(AuctionRules):
    listing_id: UUID


class BidCommand(Contract):
    amount_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    fee_quote_id: UUID
    expected_revision: StrictInt = Field(ge=1)


class BidAcceptedEventData(Contract):
    auction_id: UUID
    listing_id: UUID
    sequence: StrictInt = Field(ge=1)
    revision: StrictInt = Field(ge=1)
    current_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    currency: Literal['USD', 'LBP']
    ends_at: AwareDatetime
    bidder_id: UUID
    previous_leader_id: UUID | None
    leader_id: UUID


class AuctionTimingV1(Contract):
    auction_id: UUID
    listing_id: UUID
    starts_at: AwareDatetime
    scheduled_ends_at: AwareDatetime
    current_ends_at: AwareDatetime
    server_time: AwareDatetime
    status: Literal['scheduled', 'live', 'ended']
    revision: StrictInt = Field(ge=1)
    rules_version: str = Field(min_length=1, max_length=100)
    extension_policy: str = Field(min_length=1, max_length=100)


class AuctionTimingPageV1(Contract):
    version: Literal[1] = 1
    items: list[AuctionTimingV1] = Field(max_length=100)
    server_time: AwareDatetime
    missing_listing_ids: list[UUID] = Field(max_length=100)
    next_cursor: UUID | None = None


def step_at(bands, amount: int) -> int:
    return next(band['step_minor'] for band in reversed(bands) if amount >= band['from_minor'])


def next_minimum(auction, bands) -> int:
    if auction['accepted_sequence'] == 0:
        return auction['opening_minor']
    return auction['current_minor'] + step_at(bands, auction['current_minor'])


class BidSourceReceipt(Contract):
    event_id: UUID
    auction_id: UUID
    sequence: StrictInt = Field(ge=1)
