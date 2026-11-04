"""V1 transport primitives; exact money never crosses a boundary as a float."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Money(Contract):
    amount: Decimal = Field(max_digits=20, decimal_places=4)
    currency: Literal['USD', 'LBP']

    @field_validator('amount', mode='before')
    @classmethod
    def finite_decimal(cls, value):
        if isinstance(value, float):
            raise ValueError('Use an exact decimal string')
        try:
            decimal = Decimal(str(value))
        except InvalidOperation:
            raise ValueError('Invalid decimal amount') from None
        if not decimal.is_finite():
            raise ValueError('Amount must be finite')
        return decimal


class Actor(Contract):
    subject_id: UUID
    organization_id: UUID | None = None
    session_id: str = Field(min_length=1, max_length=200)


class Revision(Contract):
    revision: int = Field(ge=1)


class Operation(Contract):
    id: UUID
    status: Literal['pending', 'succeeded', 'denied', 'unavailable']
    resource_id: UUID | None = None
    request_id: str


class EventEnvelope(Contract):
    model_config = ConfigDict(extra='forbid', frozen=True)
    specversion: Literal['1.0'] = '1.0'
    id: UUID = Field(default_factory=uuid4)
    type: str = Field(pattern=r'^[a-z][a-z0-9.-]+\.v[1-9][0-9]*$')
    source: str = Field(pattern=r'^[a-z][a-z-]+$')
    subject: str = Field(min_length=1, max_length=200)
    time: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    data: dict[str, Any]
