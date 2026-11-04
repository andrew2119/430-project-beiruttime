"""pricing.quotes.v1: integer minor-unit snapshots, never floating point."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from bt_contracts_core.models import Contract

MAX_MINOR = 9_000_000_000_000

class QuoteRequest(Contract):
    subject_id: UUID
    subject_revision: StrictInt = Field(ge=1)
    purpose: Literal['bid', 'offer', 'purchase', 'business_quote']
    currency: Literal['USD', 'LBP']
    price_minor: StrictInt = Field(gt=0, le=MAX_MINOR)
    # No real commercial schedule has been approved. This opt-in is always labeled sample.
    schedule_id: Literal['sample-v1']
    source: Literal['sample', 'listing'] = 'sample'

    @model_validator(mode='after')
    def source_purpose(self):
        if self.source == 'listing' and self.purpose != 'purchase':
            raise ValueError('A listing-bound quote is for a fixed-price purchase')
        return self

class QuoteReview(QuoteRequest):
    quote_revision: StrictInt = Field(ge=1)
    payable_minor: StrictInt = Field(gt=0, le=MAX_MINOR * 2)

class CurrencyExponents(Contract):
    USD: Literal[2] = 2
    LBP: Literal[2] = 2


class SamplePolicy(Contract):
    buyer_fee_bps: Literal[300]
    seller_commission_bps: Literal[500]
    shipping: Literal['sample_zero']
    tax: Literal['sample_zero']
    fx: Literal['not_applied']
    currency_exponents: CurrencyExponents


class QuoteSnapshot(QuoteRequest):
    source_verified: StrictBool = False
    id: UUID
    owner_id: UUID
    revision: StrictInt = Field(ge=1)
    minor_unit_exponent: Literal[2]
    buyer_fee_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    seller_commission_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    seller_net_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    shipping_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    tax_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    payable_minor: StrictInt = Field(gt=0, le=MAX_MINOR * 2)
    sample: Literal[True]
    rounding: Literal['half_up']
    fx: None
    commission_basis: Literal['price_excluding_buyer_fee_shipping_tax']
    policy: SamplePolicy
    created_at: AwareDatetime
    expires_at: AwareDatetime
    reviewed_at: AwareDatetime | None

    @model_validator(mode='after')
    def balanced(self):
        if self.source_verified != (self.source == 'listing'):
            raise ValueError('Invalid quote source authority')
        if self.price_minor + self.buyer_fee_minor + self.shipping_minor + self.tax_minor != self.payable_minor:
            raise ValueError('Unbalanced buyer snapshot')
        if self.price_minor - self.seller_commission_minor != self.seller_net_minor:
            raise ValueError('Unbalanced seller snapshot')
        if self.expires_at <= self.created_at:
            raise ValueError('Invalid quote lifetime')
        return self


class ValidatedReservationQuote(Contract):
    quote_id: UUID
    buyer_id: UUID
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    currency: Literal['USD', 'LBP']
    total_minor: StrictInt = Field(ge=0, le=MAX_MINOR * 2)
    expires_at: AwareDatetime
    status: Literal['valid']


class OfferDraftRequest(Contract):
    subject_id: UUID
    subject_revision: StrictInt = Field(ge=1)
    currency: Literal['USD', 'LBP']
    amount_minor: StrictInt = Field(gt=0, le=MAX_MINOR)

class OfferDraftUpdate(OfferDraftRequest):
    expected_revision: StrictInt = Field(ge=1)
