"""pricing-current/v2: exact current or retained snapshots; never payment authority."""
from uuid import UUID
from typing import Literal
from pydantic import AwareDatetime, StrictInt, StrictBool, Field, model_validator
from bt_contracts_core.models import Contract


class CurrentQuote(Contract):
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    source_id: UUID
    source_revision: StrictInt = Field(ge=1)
    kind: Literal['offer', 'brand', 'repair', 'purchase', 'prebid', 'winner']
    listing_id: UUID | None = None
    listing_revision: StrictInt | None = None
    assessment_id: UUID | None = None
    assessment_revision: StrictInt | None = None
    organization_id: UUID | None = None
    currency: Literal['USD', 'LBP']
    total_minor: StrictInt = Field(gt=0, le=18_000_000_000_000)
    expires_at: AwareDatetime
    accepted_at: AwareDatetime | None = None
    selected_line_ids: list[UUID] = Field(default_factory=list, max_length=40)
    terms_digest: str | None = None
    schedule_id: Literal['sample-v1']
    policy_revision: Literal[1]
    rounding: Literal['half_up']
    status: Literal['valid']


class AcceptedFeeLines(Contract):
    assessment: StrictBool = False
    return_transport: StrictBool = False


class CurrentQuoteV3(CurrentQuote):
    currency: Literal['USD']
    expires_at: AwareDatetime | None
    schedule_id: Literal['usd-v2', 'usd-job-v2']
    policy_revision: Literal[2]
    economics: Literal['preview', 'committed']
    execution_authority: Literal['not_granted'] = 'not_granted'
    accepted_fee_lines: AcceptedFeeLines = Field(default_factory=AcceptedFeeLines)


class RetainedFinancialQuote(Contract):
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    source_id: UUID
    source_revision: StrictInt = Field(ge=1)
    currency: Literal['USD', 'LBP']
    price_minor: StrictInt = Field(gt=0, le=9_000_000_000_000)
    buyer_fee_minor: StrictInt = Field(ge=0)
    seller_commission_minor: StrictInt = Field(ge=0)
    seller_net_minor: StrictInt = Field(ge=0)
    shipping_minor: StrictInt = Field(ge=0)
    tax_minor: StrictInt = Field(ge=0)
    payable_minor: StrictInt = Field(gt=0, le=18_000_000_000_000)
    schedule_id: Literal['sample-v1', 'usd-v2', 'usd-job-v2']
    policy_revision: Literal[1, 2]
    rounding: Literal['half_up']
    minor_unit_exponent: Literal[2]
    sample: StrictBool
    policy: dict
    expires_at: AwareDatetime | None
    reviewed_at: AwareDatetime | None
    selected_line_ids: list[UUID] = Field(default_factory=list, max_length=40)
    terms_digest: str | None = None
    state: str | None = Field(default=None, max_length=40)
    return_fee_minor: StrictInt | None = Field(default=None, ge=0)
    accepted_fee_lines: AcceptedFeeLines = Field(default_factory=AcceptedFeeLines)
    authority: Literal['retained_read_only']

    @model_validator(mode='after')
    def balanced(self):
        if (self.price_minor + self.buyer_fee_minor + self.shipping_minor + self.tax_minor != self.payable_minor
                or self.price_minor - self.seller_commission_minor != self.seller_net_minor):
            raise ValueError('Retained exact economics must balance')
        return self
