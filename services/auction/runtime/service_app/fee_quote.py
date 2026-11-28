"""Private admission projection of the current USD preview; Pricing owns rates."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

PRICING_MAX_MINOR = 9_000_000_000_000


class BidFeePolicy(BaseModel):
    model_config = ConfigDict(extra='ignore')
    revision: StrictInt = Field(ge=1)


class BidFeeSnapshot(BaseModel):
    # The provider also returns seller/policy detail. Never project it into public Auction DTOs.
    model_config = ConfigDict(extra='ignore')
    id: UUID
    owner_id: UUID
    subject_id: UUID
    subject_revision: StrictInt = Field(ge=1)
    revision: StrictInt = Field(ge=1)
    purpose: Literal['bid', 'offer', 'purchase', 'business_quote']
    currency: Literal['USD']
    price_minor: StrictInt = Field(gt=0, le=PRICING_MAX_MINOR)
    buyer_fee_minor: StrictInt = Field(ge=0, le=PRICING_MAX_MINOR)
    shipping_minor: StrictInt = Field(ge=0, le=PRICING_MAX_MINOR)
    tax_minor: StrictInt = Field(ge=0, le=PRICING_MAX_MINOR)
    payable_minor: StrictInt = Field(gt=0, le=PRICING_MAX_MINOR * 2)
    schedule_id: Literal['usd-v2']
    source: Literal['sample', 'listing']
    source_verified: StrictBool
    sample: StrictBool
    minor_unit_exponent: Literal[2]
    rounding: Literal['half_up']
    created_at: AwareDatetime
    expires_at: AwareDatetime
    reviewed_at: AwareDatetime | None = None
    policy: BidFeePolicy | None = None

    @model_validator(mode='after')
    def coherent(self):
        if self.payable_minor != self.price_minor + self.buyer_fee_minor + self.shipping_minor + self.tax_minor:
            raise ValueError('Unbalanced quote')
        if self.expires_at <= self.created_at:
            raise ValueError('Invalid quote lifetime')
        if self.reviewed_at is not None and not self.created_at <= self.reviewed_at < self.expires_at:
            raise ValueError('Invalid review time')
        return self
