"""Recipient-private binding between source admission and durable Inbox."""
from uuid import UUID
from pydantic import Field, StrictInt
from bt_contracts_core.models import Contract


class BidNoticeReceipt(Contract):
    event_id: UUID
    notice_id: UUID
    auction_id: UUID
    sequence: StrictInt = Field(ge=1)
    inbox_id: UUID | None
