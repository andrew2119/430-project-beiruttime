"""Consumer projection of pricing.quotes.v1; Pricing alone calculates amounts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator
from bt_contracts_core.errors import PublicError

MAX_MINOR = 9_000_000_000_000


class PublicationQuote(BaseModel):
    # Store only the private publication terms, never an unrelated upstream payload.
    model_config = ConfigDict(extra="ignore")
    id: UUID
    owner_id: UUID
    revision: StrictInt = Field(ge=1)
    subject_id: UUID
    subject_revision: StrictInt = Field(ge=1)
    purpose: Literal["purchase"]
    source: Literal["sample"]
    source_verified: Literal[False]
    schedule_id: Literal["usd-v2"]
    currency: Literal["USD"]
    price_minor: StrictInt = Field(gt=0, le=MAX_MINOR)
    minor_unit_exponent: Literal[2]
    buyer_fee_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    seller_commission_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    seller_net_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    shipping_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    tax_minor: StrictInt = Field(ge=0, le=MAX_MINOR)
    payable_minor: StrictInt = Field(gt=0, le=MAX_MINOR * 2)
    sample: Literal[True]
    rounding: Literal["half_up"]
    fx: None
    commission_basis: Literal["price_excluding_buyer_fee_shipping_tax"]
    policy: dict
    created_at: AwareDatetime
    expires_at: AwareDatetime
    reviewed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def balanced(self):
        if self.price_minor + self.buyer_fee_minor + self.shipping_minor + self.tax_minor != self.payable_minor:
            raise ValueError("Unbalanced buyer snapshot")
        if self.price_minor - self.seller_commission_minor != self.seller_net_minor:
            raise ValueError("Unbalanced seller snapshot")
        if self.expires_at <= self.created_at:
            raise ValueError("Invalid quote lifetime")
        if self.policy != {
            "revision": 2,
            "buyer_fee_bps": 300,
            "seller_commission_bps": 500,
            "shipping": "sample_zero",
            "tax": "sample_zero",
            "fx": "not_applied",
            "currency_exponents": {"USD": 2, "LBP": 2},
        }:
            raise ValueError("Unknown publication schedule")
        return self


def publication_quote(value, *, body, row, owner_id, accepted_at: datetime):
    try:
        quote = PublicationQuote.model_validate(value)
        facts = row["facts"]
        if isinstance(facts, str):
            import json

            facts = json.loads(facts)
        if (
            quote.id != body.fee_quote_id
            or quote.subject_id != row["id"]
            or quote.subject_revision != row["revision"]
            or quote.owner_id != owner_id
            or quote.schedule_id != body.rules_version
            or quote.price_minor != facts["price_minor"]
            or quote.currency != facts["currency"]
            or quote.created_at > accepted_at
            or quote.expires_at <= accepted_at
        ):
            raise ValueError("Quote does not bind this publication")
        return quote.model_dump(mode="json")
    except (ValidationError, ValueError, TypeError, KeyError):
        raise PublicError(
            "fee_quote_mismatch", "Review a current quote for this listing revision.", status=409
        ) from None
