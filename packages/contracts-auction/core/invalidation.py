"""Event references for current Auction reads."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt

from bt_contracts_core.models import Contract


class ListingPublished(Contract):
    listing_id: UUID
    revision: StrictInt = Field(ge=1)
    seller_id: UUID
    organization_id: UUID | None
    status: Literal['published']
    is_demo: StrictBool


class BusinessStatusChanged(Contract):
    business_id: UUID
    state: Literal['active', 'revoked']
    revision: StrictInt = Field(ge=1)


class MembershipChanged(Contract):
    subject_id: UUID
    business_id: UUID
    state: Literal['active', 'suspended', 'revoked']
    revision: StrictInt = Field(ge=1)
    revoke_sessions: StrictBool


class ContactVerified(Contract):
    subject_id: UUID
    channel: Literal['email', 'phone']
    revision: StrictInt = Field(ge=1)
    sample: StrictBool


class LotInvalidation(Contract):
    auction_id: UUID
    listing_id: UUID
    revision: StrictInt = Field(ge=1)
    end_version: StrictInt = Field(ge=1)


class TimingUpdated(LotInvalidation):
    ends_at: AwareDatetime
    mode: Literal['bidding']


class ListingRevised(LotInvalidation):
    listing_revision: StrictInt = Field(ge=1)


class ListingEditAborted(Contract):
    operation_id: UUID
    listing_id: UUID
    watch_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    auction_id: UUID | None
    auction_revision: StrictInt | None = Field(ge=1)
