"""Communications events v2 and durable payment availability receipts."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, field_validator
from bt_contracts_core.models import Contract
from bt_contracts.comms.inbox.models import NoticeInput
from bt_contracts.comms.bid_notices.v2 import OutbidV2


class QuoteCreatedV3(NoticeInput):
    kind: Literal['quote_ready']
    resource_revision: StrictInt = Field(ge=1)


class PaymentActionRequiredV3(Contract):
    order_id: UUID
    buyer_id: UUID
    revision: StrictInt = Field(ge=1)
    sample: StrictBool = False


class PaymentNoticeReceiptV3(Contract):
    event_id: UUID
    notice_id: UUID
    order_id: UUID
    buyer_id: UUID
    notified_at: AwareDatetime
    verified_delivery_recorded: Literal[True]

    @field_validator('verified_delivery_recorded', mode='before')
    @classmethod
    def verified(cls, value):
        if value is not True:
            raise ValueError('Verified delivery must be recorded')
        return value


OPERATIONS = {
    'orders.payment-action-required.v3': ('orders', PaymentActionRequiredV3),
    'pricing.quote-created.v3': ('pricing', QuoteCreatedV3),
    'auction.outbid.v2': ('auction', OutbidV2),
    'payment_notice_receipt': ('POST', '/internal/v3/payment-notices'),
    'payment_notice_lookup': ('GET', '/internal/v2/inbox/payment-notices/{event_id}'),
}
