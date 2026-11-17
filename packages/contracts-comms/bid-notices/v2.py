"""Required outbid facts contain no private competition settings."""
from typing import Literal
from uuid import UUID
from pydantic import Field, StrictBool, StrictInt
from bt_contracts_core.models import Contract


class OutbidV2(Contract):
    auction_id: UUID
    recipient_id: UUID
    revision: StrictInt = Field(ge=1)
    sequence: StrictInt = Field(ge=1)
    reason: Literal['displaced_holder', 'immediately_beaten_challenger']
    sample: StrictBool = False


OPERATIONS = {'auction.outbid.v2': ('auction', OutbidV2)}
