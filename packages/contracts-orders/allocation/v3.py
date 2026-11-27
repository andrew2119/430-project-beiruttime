"""Durable Communications receipt; unconfirmed delivery never starts payment time."""

from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import AwareDatetime
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
