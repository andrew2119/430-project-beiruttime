"""Consumer validation of published contracts-auction/core/index.ts v1.

These are read DTOs only; no Auction rules, persistence or bid engine lives here.
Unknown fields (especially the seller-private reserve) fail closed.
"""
from typing import Literal
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, field_validator
from .models import MAX_MINOR, PublicModel, masked_label

class Band(PublicModel):
    from_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    step_minor: StrictInt = Field(ge=1, le=MAX_MINOR)


class Snapshot(PublicModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    listing_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    currency: Literal['USD', 'LBP']
    opening_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    current_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    next_minimum_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    increment_bands: list[Band] = Field(min_length=1, max_length=20)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    server_time: AwareDatetime
    revision: StrictInt = Field(ge=1, le=MAX_MINOR)
    accepted_sequence: StrictInt = Field(ge=0, le=MAX_MINOR)
    rules_version: Literal['ordinary.v1']
    extension_policy: Literal['none.v1']
    high_value_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    reserve_set: StrictBool
    leader: str | None
    status: Literal['live', 'scheduled', 'ended']
    _masked_leader = field_validator('leader')(masked_label)

class Bid(PublicModel):
    sequence: StrictInt = Field(ge=1, le=MAX_MINOR)
    bidder: str = Field(min_length=1, max_length=100)
    amount_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    automatic: StrictBool
    received_at: AwareDatetime
    _masked_bidder = field_validator('bidder')(masked_label)

class History(PublicModel):
    items: list[Bid] = Field(max_length=50)
    has_more: StrictBool
    next_sequence: StrictInt = Field(ge=0, le=MAX_MINOR)
    snapshot: Snapshot
