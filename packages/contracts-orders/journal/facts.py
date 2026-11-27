"""Read-only Orders payment facts v1. Unknown legacy bindings never qualify as paid authority."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, StrictBool
from bt_contracts_core.models import Contract


class PaidOrderFact(Contract):
    id: UUID
    order_id: UUID
    watch_id: UUID
    listing_id: UUID
    buyer_id: UUID
    seller_id: UUID
    organization_id: UUID | None
    quote_id: UUID
    quote_revision: StrictInt | None
    listing_revision: StrictInt | None
    seller_type: Literal["private", "dealer", "brand"] | None
    journal_group_id: UUID | None
    state: Literal["awaiting_payment", "payment_unknown", "expired_fenced", "paid_held"]
    currency: Literal["USD", "LBP"]
    total_minor: StrictInt = Field(ge=0, le=9000000000000000)
    revision: StrictInt = Field(ge=1)
    deadline: AwareDatetime
    is_demo: StrictBool
    payment_authority: Literal[False]
    paid: StrictBool
    simulated: Literal[True]
    payout_authorized: Literal[False]
