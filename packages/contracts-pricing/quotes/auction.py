"""Additive close-command adapter; submitted money never replaces source proof."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt
from bt_contracts_core.models import Contract


class AuctionQuoteContext(Contract):
    auction_id: UUID
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    buyer_id: UUID
    seller_id: UUID
    seller_organization_id: UUID | None
    revision: StrictInt = Field(ge=1)
    end_version: StrictInt = Field(ge=1)
    close_version: StrictInt = Field(ge=0)
    mode: Literal['bidding', 'closed_winner']
    currency: Literal['USD', 'LBP']
    price_minor: StrictInt = Field(gt=0, le=9_000_000_000_000)
    ends_at: AwareDatetime


class AuctionWinnerSource(Contract):
    auction_id: UUID
    source_id: UUID
    watch_id: UUID
    listing_id: UUID
    buyer_id: UUID
    seller_id: UUID
    organization_id: UUID | None
    currency: Literal['USD', 'LBP']
    price_minor: StrictInt = Field(gt=0, le=9_000_000_000_000)
    end_version: StrictInt = Field(ge=1)
    close_version: StrictInt = Field(ge=1)
    kind: Literal['winner']


class AuctionWinnerReceipt(Contract):
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    listing_id: UUID
    source_id: UUID
    currency: Literal['USD', 'LBP']
    price_minor: StrictInt = Field(gt=0, le=9_000_000_000_000)
    total_minor: StrictInt = Field(gt=0, le=18_000_000_000_000)
