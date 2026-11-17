"""Durable Communications receipt; unconfirmed delivery never starts payment time."""

from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import AwareDatetime, Field, StrictInt
from bt_contracts_core.models import Contract


class PaymentNoticeReceipt(Contract):
    event_id: UUID
    notice_id: UUID
    order_id: UUID
    buyer_id: UUID
    notified_at: AwareDatetime
    verified_delivery_recorded: Literal[True]


def notice_matches(receipt: PaymentNoticeReceipt, intent, order, now: datetime):
    return (
        receipt.event_id == intent["event_id"]
        and receipt.order_id == order["id"] == intent["order_id"]
        and receipt.buyer_id == order["buyer_id"] == intent["buyer_id"]
        and intent["created_at"] <= receipt.notified_at <= now
    )


class CurrentCommitment(Contract):
    schema_version: Literal["orders-commitment.v3"] = "orders-commitment.v3"
    order_id: UUID
    watch_id: UUID
    buyer_id: UUID
    organization_id: UUID | None
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    order_revision: StrictInt = Field(ge=1)
    watch_revision: StrictInt = Field(ge=1)
    state: str
    current: bool
    notified_at: AwareDatetime | None
    deadline: AwareDatetime | None
    payment_authority: Literal[False] = False


class UnpaidReleaseReceipt(Contract):
    schema_version: Literal["orders-unpaid-release.v3"] = "orders-unpaid-release.v3"
    order_id: UUID
    watch_id: UUID
    order_revision: StrictInt = Field(ge=1)
    released_at: AwareDatetime
    attempt_count: StrictInt = Field(ge=0)
    origin: Literal["expiry", "historical"]
    allocation_authority: Literal[False] = False
