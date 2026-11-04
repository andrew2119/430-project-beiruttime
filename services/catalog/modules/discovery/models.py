"""Closed public read models: private files, bidder IDs and maxima have no field."""
import re
from decimal import Decimal
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from bt_contracts_core.models import Money

MAX_MINOR = 9_000_000_000_000_000


def masked_label(value: str | None):
    if value is not None and (not value.strip() or len(value)>100 or '@' in value or any(ord(c)<32 for c in value) or re.fullmatch(r'[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}',value)):
        raise ValueError('Expected a masked public bidder reference')
    return value


class PublicModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class PublicMoney(Money):
    @model_validator(mode='after')
    def exact_minor(self):
        scale = Decimal(100)
        minor = self.amount * scale
        if minor != minor.to_integral_value() or not 0 <= minor <= MAX_MINOR:
            raise ValueError('Money must be finite integer minor units')
        return self

class Photo(PublicModel):
    id: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=500)
    alt: str = Field(min_length=1, max_length=500)
    alt_ar: str | None = Field(default=None, max_length=500)
    credit: str | None = Field(default=None, max_length=6000)

    @field_validator('url')
    @classmethod
    def public_only(cls, value):
        if not re.match(r'^/(?:demo/watches/[A-Za-z0-9_./-]+|api/(?:web|mobile)/v1/catalog/v1/listings/[A-Za-z0-9_-]+/photos/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+)$', value) or any(c in value for c in ('..', '\\', '?', '#', '%')) or any(c.isspace() for c in value):
            raise ValueError('Not a public media reference')
        return value

class WatchSummary(PublicModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    revision: StrictInt = Field(ge=1, le=MAX_MINOR)
    title: str = Field(min_length=1, max_length=320)
    brand: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=160)
    location: str = Field(min_length=1, max_length=160)
    price: PublicMoney | None
    sale_mode: Literal['fixed', 'auction', 'offer']
    sale_state: Literal['available', 'not_started', 'reserved', 'sold', 'ended', 'unavailable']
    thumbnail: Photo | None = None
    published_at: AwareDatetime
    ends_at: AwareDatetime | None = None
    demo: bool = False

class Seller(PublicModel):
    display_name: str = Field(min_length=1, max_length=160)
    kind: Literal['private', 'dealer', 'brand']
    completed_sales: StrictInt | None = Field(default=None, ge=0, le=MAX_MINOR)
    joined_at: AwareDatetime | None = None

class Assurance(PublicModel):
    kind: Literal['private_inspection', 'official_business']
    status: Literal['pending', 'passed', 'failed', 'inconclusive', 'onboarded', 'unavailable']

class WatchDetail(WatchSummary):
    reference: str | None = Field(default=None, max_length=100)
    year: StrictInt | None = Field(default=None, ge=1800, le=2100)
    component_wear: dict[Literal['case', 'dial', 'crystal', 'bracelet', 'movement'], str] = Field(default_factory=dict, max_length=5)
    description: str = Field(max_length=10000)
    condition: str = Field(max_length=2000)
    included_items: list[str] = Field(max_length=30)
    modified: bool
    modified_parts: list[str] = Field(max_length=30)
    photos: list[Photo] = Field(max_length=20)
    media_state: Literal['available','unavailable'] = 'available'
    seller: Seller
    assurance: Assurance

    @field_validator('component_wear')
    @classmethod
    def bounded_wear(cls, values):
        if any(len(value) > 2000 for value in values.values()):
            raise ValueError('Invalid wear disclosure length')
        return values

    @field_validator('included_items', 'modified_parts')
    @classmethod
    def bounded_items(cls, values):
        if any(not value or len(value) > 1500 for value in values):
            raise ValueError('Invalid disclosure length')
        return values

    @model_validator(mode='after')
    def separate_assurance(self):
        if self.seller.kind == 'private':
            if self.assurance.kind != 'private_inspection' or self.assurance.status == 'onboarded':
                raise ValueError('Private watches require an explicit inspection state')
        elif self.assurance.kind != 'official_business' or self.assurance.status not in ('onboarded', 'unavailable'):
            raise ValueError('Business assurance must not imply an independent inspection')
        if self.modified and not self.modified_parts:
            raise ValueError('Modified parts must be disclosed')
        if not self.modified and self.modified_parts:
            raise ValueError('Inconsistent modification disclosure')
        return self

class SearchPage(PublicModel):
    items: list[WatchSummary]
    next_cursor: str | None
    server_time: AwareDatetime

class PublicBid(PublicModel):
    sequence: StrictInt = Field(ge=1, le=MAX_MINOR)
    bidder_label: str = Field(min_length=1, max_length=100)
    amount: PublicMoney
    accepted_at: AwareDatetime
    _masked_bidder = field_validator('bidder_label')(masked_label)

class AuctionSnapshot(PublicModel):
    auction_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    listing_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    revision: StrictInt = Field(ge=1, le=MAX_MINOR)
    last_sequence: StrictInt = Field(ge=0, le=MAX_MINOR)
    current_price: PublicMoney
    opening_price: PublicMoney | None = None
    server_time: AwareDatetime
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime
    end_version: StrictInt = Field(ge=1, le=MAX_MINOR)
    status: Literal['scheduled', 'open', 'ended', 'cancelled']
    bids: list[PublicBid] = Field(max_length=50)
    history_truncated: bool

    @model_validator(mode='after')
    def ordered_history(self):
        sequences = [bid.sequence for bid in self.bids]
        if len(set(sequences)) != len(sequences) or any(seq > self.last_sequence for seq in sequences):
            raise ValueError('History must reference canonical accepted sequences')
        return self

class AuctionRead(PublicModel):
    state: Literal['available', 'unavailable', 'not_started']
    snapshot: AuctionSnapshot | None = None

    @model_validator(mode='after')
    def bind_state(self):
        if (self.state == 'available') != (self.snapshot is not None):
            raise ValueError('Auction state must bind its canonical snapshot')
        return self
