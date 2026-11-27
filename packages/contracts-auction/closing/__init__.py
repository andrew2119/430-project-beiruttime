from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt, StrictBool
from bt_contracts_core.models import Contract


class CloseAuction(Contract):
    expected_end_version: StrictInt = Field(ge=1)


class CloseResult(Contract):
    auction_id: UUID
    status: Literal[
        "not_closed", "no_sale", "allocation_pending", "allocation_denied", "closed"
    ]
    end_version: StrictInt | None = None
    close_version: StrictInt | None = None
    mode: str | None = None
    reason: str | None = None
    winner: str | None = None
    closing_minor: StrictInt | None = None
    currency: Literal["USD", "LBP"] | None = None
    order_available: StrictBool = False
    # Only authenticated own-result reads populate these two fields.
    won: StrictBool | None = None
    order_id: UUID | None = None
