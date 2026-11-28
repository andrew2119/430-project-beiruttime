"""Development-only frozen financial DTOs while the producer is absent."""

import importlib.util
import sys
from datetime import datetime
from types import ModuleType
from typing import Literal
from uuid import UUID

import pytest
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt


class CurrentQuoteV3(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    source_id: UUID
    source_revision: StrictInt = Field(ge=1)
    kind: Literal["purchase", "winner", "offer", "prebid"]
    listing_id: UUID | None = None
    listing_revision: StrictInt | None = None
    currency: Literal["USD"]
    total_minor: StrictInt = Field(gt=0)
    expires_at: AwareDatetime | None
    accepted_at: AwareDatetime | None = None
    selected_line_ids: list[UUID] = []
    terms_digest: str | None = None
    schedule_id: Literal["usd-v2"]
    policy_revision: Literal[2]
    rounding: Literal["half_up"]
    status: Literal["valid"]
    economics: Literal["committed", "preview"]
    execution_authority: Literal["not_granted"]


class RetainedFinancialQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    source_id: UUID
    source_revision: StrictInt = Field(ge=1)
    currency: Literal["USD"]
    schedule_id: Literal["usd-v2"]
    policy_revision: Literal[2]
    rounding: Literal["half_up"]
    selected_line_ids: list[UUID]
    terms_digest: str | None
    price_minor: StrictInt = Field(ge=0)
    buyer_fee_minor: StrictInt = Field(ge=0)
    seller_commission_minor: StrictInt = Field(ge=0)
    seller_net_minor: StrictInt = Field(ge=0)
    shipping_minor: StrictInt = Field(ge=0)
    tax_minor: StrictInt = Field(ge=0)
    payable_minor: StrictInt = Field(gt=0)
    minor_unit_exponent: Literal[2]
    sample: bool
    policy: dict
    expires_at: datetime | None
    reviewed_at: AwareDatetime
    authority: Literal["retained_read_only"]


@pytest.fixture(autouse=True)
def missing_pricing_contract(monkeypatch):
    name = "bt_contracts.pricing.quotes.current"
    try:
        available = importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        available = False
    if available:
        return
    module = ModuleType(name)
    module.CurrentQuoteV3 = CurrentQuoteV3
    module.RetainedFinancialQuote = RetainedFinancialQuote
    monkeypatch.setitem(sys.modules, name, module)
