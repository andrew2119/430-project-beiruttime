from typing import Literal
from uuid import UUID
from pydantic import StrictInt, Field, AwareDatetime
from bt_contracts_core.models import Contract


class JournalGroup(Contract):
    id: UUID
    order_id: UUID
    attempt_id: UUID
    currency: Literal["USD", "LBP"]
    total_minor: StrictInt = Field(gt=0, le=9000000000000000)
    simulated: Literal[True]
    posted_at: AwareDatetime


class JournalEntry(Contract):
    account: Literal["simulated_clearing", "buyer_held"]
    amount_minor: StrictInt
