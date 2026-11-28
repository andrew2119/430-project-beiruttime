"""Simulated checkout v1: no card, wallet credential or real charging API."""

from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt
from bt_contracts_core.models import Contract

Route = Literal["card", "whish", "omt"]


class SelectPaymentMethod(Contract):
    expected_revision: StrictInt = Field(ge=1)
    route: Route


class StartPayment(Contract):
    expected_revision: StrictInt = Field(ge=1)
    route: Route
    # Closed winners may allocate before review. Their buyer explicitly accepts
    # the displayed immutable economics when starting the simulated attempt.
    quote_revision: StrictInt | None = Field(default=None, ge=1)
    total_minor: StrictInt | None = Field(default=None, ge=1, le=9000000000000000)
    currency: Literal["USD", "LBP"] | None = None


class Simulate(Contract):
    outcome: Literal["pending", "declined", "confirmed"]


class PaymentCallback(Contract):
    event_id: UUID
    attempt_id: UUID
    order_id: UUID
    buyer_id: UUID
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    reference: str = Field(min_length=1, max_length=100)
    route: Route
    currency: Literal["USD", "LBP"]
    total_minor: StrictInt = Field(ge=1, le=9000000000000000)
    outcome: Literal["pending", "declined", "confirmed"]
    sequence: StrictInt = Field(ge=1, le=9000000000000000)
