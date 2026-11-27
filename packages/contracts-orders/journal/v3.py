"""Versioned movement requests; permission comes from a current Orders policy read."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, model_validator
from bt_contracts_core.models import Contract
from .v2 import AcceptedMoney, SavedSimulatedMethod

Kind = Literal['refund', 'release', 'failed_authentication', 'job_fee']
Minor = StrictInt


class SavedSimulatedRecipient(Contract):
    id: UUID
    owner_id: UUID
    organization_id: UUID | None
    revision: Minor = Field(ge=1)
    route: Literal['card', 'whish', 'omt']
    reference: str = Field(pattern=r'^SIM-RECIPIENT-[0-9a-f-]{36}$')

    @model_validator(mode='after')
    def exact_reference(self):
        if self.reference != 'SIM-RECIPIENT-' + str(self.id):
            raise ValueError('Use the exact saved simulated recipient')
        return self


class ReleaseAmounts(Contract):
    gross_minor: Minor = Field(gt=0, le=18_000_000_000_000)
    business_fee_minor: Minor = Field(ge=0, le=18_000_000_000_000)
    buyer_fee_minor: Minor = Field(ge=0, le=18_000_000_000_000)
    shipping_minor: Minor = Field(ge=0, le=18_000_000_000_000)
    tax_minor: Minor = Field(ge=0, le=18_000_000_000_000)
    transfer_minor: Minor = Field(ge=0, le=18_000_000_000_000)

    @model_validator(mode='after')
    def balanced(self):
        if self.gross_minor != (self.business_fee_minor + self.buyer_fee_minor
                + self.shipping_minor + self.tax_minor + self.transfer_minor):
            raise ValueError('Release gross must equal deductions plus transfer')
        return self


class Movement(Contract):
    schema_version: Literal[3] = 3
    operation_id: UUID
    order_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: Minor = Field(ge=1)
    quote_id: UUID
    quote_revision: Minor = Field(ge=1)
    source_id: UUID
    source_revision: Minor = Field(ge=1)
    kind: Kind
    amount_minor: Minor = Field(gt=0, le=18_000_000_000_000)
    currency: Literal['USD'] = 'USD'
    # Immutable simulated destination for refunds/releases; collection uses a saved method.
    recipient_id: UUID
    method: SavedSimulatedMethod | None = None
    destination: SavedSimulatedRecipient | None = None
    original_payment_attempt_id: UUID | None = None
    release_amounts: ReleaseAmounts | None = None

    @model_validator(mode='after')
    def method_required(self):
        if (self.kind in {'failed_authentication', 'job_fee'}) != (self.method is not None):
            raise ValueError('Collection alone requires a saved simulated method')
        if (self.kind in {'refund', 'release'}) != (self.destination is not None):
            raise ValueError('Outgoing funds require an immutable saved recipient')
        if (self.kind == 'refund') != (self.original_payment_attempt_id is not None):
            raise ValueError('Refund binds the original confirmed payment attempt')
        if (self.kind == 'release') != (self.release_amounts is not None):
            raise ValueError('Release alone requires gross, deductions and transfer')
        if self.release_amounts is not None and self.amount_minor != self.release_amounts.gross_minor:
            raise ValueError('Release amount must equal gross')
        return self


class CurrentAuthority(Contract):
    """Internal serialized policy result, never accepted from an HTTP caller or cache.

    The provider locks current assignment, scope, custody, decision and hold records
    in the same transaction and binds the complete request. A missing provider denies.
    """

    request: Movement
    money: AcceptedMoney
    valid_until: AwareDatetime
    permitted: bool
    responsible_actor_id: UUID
    # Refund permission must already include actual return or the approved exception.
    permitted_refund_minor: Minor = Field(ge=0)
    inspection_failed: bool = False
    private_sale: bool = False
    custody_instruction_id: UUID | None = None
    release_ready: bool = False
    # Current permission to settle accepted transport/tax after full principal refund.
    charges_ready: bool = False
    received_at: AwareDatetime | None = None
    window_ends_at: AwareDatetime | None = None
    hold: bool = True
    # Agreed fee, once: any prior collection means release cannot deduct it again.
    fee_already_collected: bool = False


class MovementResult(Contract):
    schema_version: Literal[3] = 3
    operation_id: UUID
    order_id: UUID
    state: Literal['pending', 'declined', 'confirmed']
    revision: Minor = Field(ge=1)
    amount_minor: Minor = Field(gt=0)
    currency: Literal['USD'] = 'USD'
    release_amounts: ReleaseAmounts | None = None
    recognized_fee_minor: Minor = Field(ge=0, default=0)
    journal_group_id: UUID | None
    pending_reason: Literal['reconciliation_required'] | None = None
    next_actor: UUID
    next_review_at: AwareDatetime
    simulated: Literal[True] = True


class MovementCallback(Contract):
    schema_version: Literal[3] = 3
    event_id: UUID
    request: Movement
    outcome: Literal['pending', 'declined', 'confirmed']
    sequence: Minor = Field(ge=1, le=9_000_000_000_000_000)


class FinancialReadiness(Contract):
    movement_status: Literal['none', 'refund_pending', 'refunded', 'release_pending', 'released', 'reconciliation']
    schema_version: Literal[3] = 3
    order_id: UUID
    revision: Minor = Field(ge=1)
    state: Literal['paid_held', 'pending', 'unpaid']
    held_minor: Minor = Field(ge=0)
    reserved_minor: Minor = Field(ge=0)
    currency: Literal['USD'] = 'USD'
    simulated: Literal[True] = True
    payment_authority: Literal[False] = False
