"""Reference-only offer state facts; no notification/payment promise."""
from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt
from bt_contracts_core.models import Contract


class OfferFact(Contract):
    offer_id: UUID
    listing_id: UUID
    buyer_id: UUID
    seller_id: UUID
    seller_organization_id: UUID | None
    revision: StrictInt = Field(ge=1)
    state: Literal['open', 'accepted', 'rejected', 'lost', 'closed', 'expired']
