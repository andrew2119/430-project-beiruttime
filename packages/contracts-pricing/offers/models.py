"""offers/v1: current-party offers, never a second physical allocation authority."""
from uuid import UUID
from typing import Literal
from pydantic import AwareDatetime, Field, StrictInt
from bt_contracts_core.models import Contract


class MakeOffer(Contract):
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    amount_minor: StrictInt = Field(gt=0, le=9_000_000_000_000)
    currency: Literal['USD', 'LBP']
    expires_at: AwareDatetime
    schedule_id: Literal['sample-v1']
    fee_quote_id: UUID


class AnswerOffer(Contract):
    expected_revision: StrictInt = Field(ge=1)
    action: Literal['accept', 'reject']
