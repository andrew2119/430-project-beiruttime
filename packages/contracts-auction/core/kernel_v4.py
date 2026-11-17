"""Versioned fixed-end decisions; persistence belongs to the auction transaction."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, StrictInt, Field, model_validator
from bt_contracts_core.models import Contract

Mode = Literal['bidding', 'first_bid_pending', 'listing_edit_pending', 'prebid_pending',
               'prebid_reserved', 'cancellation_pending', 'cancelled', 'ended_legacy_review',
               'closed_no_sale', 'closed_winner']


class KernelCommand(Contract):
    schema_version: Literal['auction-kernel.v4'] = 'auction-kernel.v4'
    operation_id: UUID
    auction_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    action: Literal['cancel', 'confirm_cancellation', 'close', 'resolve_legacy_no_sale']


class KernelReceipt(Contract):
    schema_version: Literal['auction-kernel.v4'] = 'auction-kernel.v4'
    operation_id: UUID
    auction_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    state: Literal['succeeded', 'denied', 'pending']
    code: str
    mode: Mode
    revision: StrictInt = Field(ge=1)
    server_time: AwareDatetime
    pending_reason: str | None = None
    next_actor: UUID | None = None
    next_review_at: AwareDatetime | None = None

    @model_validator(mode='after')
    def follow_up(self):
        if self.pending_reason and (self.next_actor is None or self.next_review_at is None):
            raise ValueError('Pending work requires a responsible person and review time')
        if self.state == 'pending' and not self.pending_reason:
            raise ValueError('Pending work requires a reason')
        return self


def decide(lot, action: str, now: datetime):
    """Return mode/status/code without exposing reserve, ceilings or winner identity."""
    mode = lot['mode']
    if lot.get('currency') != 'USD':
        return mode, 'pending', 'currency_reconciliation_required'
    if mode == 'ended_legacy_review' and action == 'resolve_legacy_no_sale':
        return 'closed_no_sale', 'succeeded', 'no_sale'
    if mode in ('cancelled', 'closed_no_sale', 'closed_winner', 'ended_legacy_review'):
        return mode, 'denied', 'auction_final'
    if action == 'confirm_cancellation' and mode == 'cancellation_pending':
        return 'cancelled', 'succeeded', 'cancelled'
    if now >= lot['scheduled_ends_at']:
        if action != 'close':
            return mode, 'denied', 'auction_ended'
        if mode in ('prebid_pending', 'prebid_reserved'):
            return 'ended_legacy_review', 'pending', 'legacy_outcome_review'
        if mode == 'cancellation_pending':
            return mode, 'pending', 'cancellation_pending'
        validate_close_economics(lot)
        qualifies = (lot['accepted_sequence'] > 0 and lot['leader_id'] is not None
                     and (lot['reserve_minor'] is None or lot['current_minor'] >= lot['reserve_minor']))
        return ('closed_winner', 'succeeded', 'allocation_pending') if qualifies else (
            'closed_no_sale', 'succeeded', 'no_sale')
    if action == 'close':
        return mode, 'denied', 'auction_not_ended'
    if action == 'cancel' and mode == 'cancellation_pending':
        return mode, 'pending', 'cancellation_pending'
    if action == 'cancel' and mode == 'bidding' and not lot['accepted_sequence'] and not lot['first_bid_confirmed']:
        return 'cancellation_pending', 'pending', 'cancellation_pending'
    return mode, 'denied', 'cancellation_denied'


def validate_close_economics(lot):
    """Refuse invalid retained cents before recording a sale or no-sale result."""
    for field, minimum in (('opening_minor', 1), ('current_minor', 0), ('reserve_minor', 1)):
        amount = lot[field]
        if field == 'reserve_minor' and amount is None:
            continue
        if type(amount) is not int or not minimum <= amount <= 9_000_000_000_000:
            raise ValueError('Auction result is unavailable; retained economics require review')
    if (lot['accepted_sequence'] > 0 and lot['current_minor'] < lot['opening_minor']
            or lot['reserve_minor'] is not None and lot['reserve_minor'] < lot['opening_minor']):
        raise ValueError('Auction result is unavailable; retained economics require review')


class CurrentState(Contract):
    schema_version: Literal['auction-kernel.v4'] = 'auction-kernel.v4'
    mode: Mode
    revision: StrictInt = Field(ge=1)
    end_version: StrictInt = Field(ge=1)
    close_version: StrictInt = Field(ge=0)
    status: Literal['scheduled', 'live', 'ended', 'cancelled']
    current_minor: StrictInt = Field(ge=0, le=9_000_000_000_000)
    scheduled_ends_at: AwareDatetime
    server_time: AwareDatetime
    pending_reason: str | None = None
    next_actor: UUID | None = None
    next_review_at: AwareDatetime | None = None


def current_state(lot, now: datetime, follow_up: KernelReceipt | None = None):
    """Whitelist current state; retained financial modes never extend public time."""
    if lot.get('currency') != 'USD':
        raise ValueError('Current state is unavailable; currency reconciliation is required')
    status = ('cancelled' if lot['mode'] == 'cancelled' else
              'ended' if now >= lot['scheduled_ends_at'] else
              'scheduled' if now < lot['starts_at'] else 'live')
    held = lot['mode'] in ('cancellation_pending', 'ended_legacy_review', 'closed_winner')
    if held and (follow_up is None or follow_up.auction_id != lot['id']
                 or follow_up.watch_id != lot['watch_id'] or follow_up.revision != lot['revision']
                 or follow_up.mode != lot['mode'] or not follow_up.pending_reason):
        raise ValueError('Current follow-up record is unavailable')
    return CurrentState(pending_reason=follow_up.pending_reason if held else None,
                        next_actor=follow_up.next_actor if held else None,
                        next_review_at=follow_up.next_review_at if held else None, mode=lot['mode'], revision=lot['revision'], end_version=lot['end_version'],
                        close_version=lot['close_version'], status=status,
                        current_minor=lot['current_minor'], scheduled_ends_at=lot['scheduled_ends_at'],
                        server_time=now)
