"""Orders allocation V1; persisted money uses integer minor units."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, StrictBool, field_validator
from bt_contracts_core.models import Contract


class RegisterWatch(Contract):
    watch_id: UUID
    listing_id: UUID
    seller_id: UUID
    organization_id: UUID | None = None
    listing_revision: StrictInt = Field(ge=1)
    sale_mode: Literal['fixed', 'auction', 'seller_base']
    is_demo: StrictBool = False


class ReserveWatch(Contract):
    watch_id: UUID
    quote_id: UUID
    expected_revision: StrictInt = Field(ge=1)


class FenceWatch(Contract):
    source_id: UUID
    expected_revision: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def nonblank_reason(cls,value):
        if not value.strip():
            raise ValueError('A reason is required')
        return value


class CustodyFact(Contract):
    expected_revision: StrictInt = Field(ge=1)
    actual_watch: str = Field(min_length=1, max_length=300)
    accessories: list[str] = Field(max_length=20)
    location: str = Field(min_length=1, max_length=200)
    condition: str = Field(min_length=1, max_length=2000)
    occurred_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('actual_watch','location','condition','reason')
    @classmethod
    def nonblank_fact(cls,value):
        if not value.strip():
            raise ValueError('An actual fact is required')
        return value


class Transition(Contract):
    expected_revision: StrictInt = Field(ge=1)
    state: Literal['payment_unknown', 'released', 'completed', 'paid', 'cancelled']
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def nonblank_reason(cls,value):
        if not value.strip():
            raise ValueError('A reason is required')
        return value


class CustodyReceipt(Contract):
    id: UUID
    order_id: UUID
    organization_id: UUID
    received_at: AwareDatetime
    revision: StrictInt = Field(ge=1)
    valid: Literal[True]


class ValidatedQuote(Contract):
    quote_id: UUID
    buyer_id: UUID
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    currency: Literal['USD', 'LBP']
    total_minor: StrictInt = Field(ge=0, le=9000000000000000)
    expires_at: AwareDatetime
    status: Literal['valid']
