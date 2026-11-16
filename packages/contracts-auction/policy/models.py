"""Fixed-end policy v2 with retained historical purchase read models."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt
from bt_contracts_core.models import Contract

POLICY_VERSION = 'fixed-end.v2'


class AcceptedBidPolicy(Contract):
    ends_at: AwareDatetime
    server_time: AwareDatetime
    end_version: StrictInt = Field(ge=1)
    # Read compatibility only; a legacy value has no timing effect.
    extension_policy: Literal['none.v1', 'last-two-minutes.v1'] = 'none.v1'


class ExtensionResult(Contract):
    ends_at: AwareDatetime
    end_version: StrictInt = Field(ge=1)
    extended: bool


class ConfigurePolicy(Contract):
    """No extension or auction-purchase configuration is admitted."""


class PrebidCommand(Contract):
    expected_revision: StrictInt = Field(ge=1)
    quote_id: UUID


class PolicySnapshot(Contract):
    policy_version: Literal['fixed-end.v2'] = POLICY_VERSION
    auction_id: UUID
    revision: StrictInt = Field(ge=1)
    end_version: StrictInt = Field(ge=1)
    current_ends_at: AwareDatetime
    server_time: AwareDatetime
    frozen: bool
    reserve_set: bool
    mode: str = Field(min_length=1, max_length=100)
    schedule_state: Literal['scheduled', 'live', 'ended', 'ended_legacy_review']


class SellerPolicySnapshot(PolicySnapshot):
    reserve_met: bool
    cancellation_eligible: bool


class PrebidOutcome(Contract):
    operation_id: UUID
    auction_id: UUID
    status: Literal['pending', 'succeeded', 'denied']
    code: str = Field(min_length=1, max_length=100)
    revision: StrictInt = Field(ge=1)
    order_id: UUID | None = None
    reservation_id: UUID | None = None
    quote_id: UUID | None = None


class PrebidQuoteBasis(Contract):
    auction_id: UUID
    buyer_id: UUID
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    admission_revision: StrictInt = Field(ge=1)
    current_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    listing_id: UUID
    listing_revision: StrictInt = Field(ge=1)
    currency: Literal['USD', 'LBP']
    price_minor: StrictInt = Field(ge=1, le=9_000_000_000_000_000)
    total_minor: StrictInt = Field(ge=1, le=9_000_000_000_000_000)
    mode: Literal['prebid_pending', 'prebid_reserved']
    prepared_at: AwareDatetime


class PrebidResolvedEvent(Contract):
    auction_id: UUID
    listing_id: UUID
    status: Literal['succeeded', 'denied']
    mode: Literal['prebid_pending', 'prebid_reserved']
    revision: StrictInt = Field(ge=1)
    end_version: StrictInt = Field(ge=1)

