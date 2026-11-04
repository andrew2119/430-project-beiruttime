"""communications.inbox.v1: allowlisted references, not arbitrary private URLs."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt
from bt_contracts_core.models import Contract

class NoticeInput(Contract):
    occurrence_id: str = Field(min_length=1, max_length=160)
    recipient_id: UUID
    kind: Literal['quote_ready', 'bid_accepted', 'outbid', 'reservation_ready', 'payment_required', 'case_update']
    resource_id: UUID
    resource_revision: StrictInt | None = Field(default=None, ge=1)
    resource_owner_id: UUID
    event_time: AwareDatetime
    required: bool = True
    sample: bool = False

class NoticeMutation(Contract):
    expected_revision: StrictInt = Field(ge=1)

class Preferences(Contract):
    optional_enabled: bool
    expected_revision: StrictInt = Field(ge=0)
