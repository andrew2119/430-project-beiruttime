from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt, field_validator
from bt_contracts_core.models import Contract


class Withdraw(Contract):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("A reason is required")
        return value.strip()


class WithdrawalResult(Contract):
    listing_id: UUID
    status: Literal["none", "pending", "denied", "succeeded"]
    id: UUID | None = None
    base_revision: StrictInt | None = None
    state: Literal["pending", "denied", "succeeded"] | None = None
    operation_key: str | None = None
    reason: str | None = None
    outcome: dict | None = None
    next_action: str | None = None
    code: str | None = None
