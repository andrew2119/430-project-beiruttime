"""Versioned reduction commands; source facts remain with their owners."""
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from bt_contracts_core.models import Contract


class Measurement(Contract):
    value: str = Field(pattern=r'^[0-9]{1,3}(\.[0-9])?$')
    unit: Literal['cm', 'mm']
    source: str = Field(min_length=1, max_length=160)
    method: str = Field(min_length=1, max_length=160)

    @model_validator(mode='after')
    def plausible(self):
        if not Decimal('80') <= self.millimeters <= Decimal('350'):
            raise ValueError('measurement')
        if not self.source.strip() or not self.method.strip():
            raise ValueError('measurement')
        return self

    @property
    def millimeters(self):
        return Decimal(self.value) * (10 if self.unit == 'cm' else 1)


class Binding(Contract):
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    source_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)


class Command(Binding):
    schema_version: Literal['reduction.command.v1'] = 'reduction.command.v1'
    operation_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    kind: Literal['request', 'record']
    choice_id: str = Field(min_length=1, max_length=160)
    target: Measurement
    recipient_id: UUID
    removed_link_ids: list[UUID] = Field(default_factory=list, max_length=100)
    returned_link_ids: list[UUID] = Field(default_factory=list, max_length=100)
    exception_id: UUID | None = None
    fit_confirmed: StrictBool = False
    actual_strap_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode='after')
    def distinct(self):
        for rows in (self.removed_link_ids, self.returned_link_ids):
            if len(rows) != len(set(rows)):
                raise ValueError('duplicate_parts')
        if self.kind == 'request' and (self.removed_link_ids or self.returned_link_ids or self.exception_id or self.fit_confirmed or self.actual_strap_id):
            raise ValueError('request_is_not_work')
        return self


class Choice(Contract):
    id: str = Field(min_length=1, max_length=160)
    kind: Literal['removable_links', 'strap_change']
    compatible: StrictBool


class AcceptedStrap(Contract):
    id: str = Field(min_length=1, max_length=160)
    choice_id: str = Field(min_length=1, max_length=160)
    source_revision: StrictInt = Field(ge=1)
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    compatible: StrictBool


class ReturnException(Contract):
    id: UUID
    accepted_by: UUID
    accepted_at: AwareDatetime
    source_revision: StrictInt = Field(ge=1)
    quote_revision: StrictInt = Field(ge=1)
    recipient_id: UUID
    link_ids: list[UUID] = Field(min_length=1, max_length=100)
    basis: Literal['supplier_exchange', 'non_buyer_owned']


class Authority(Binding):
    schema_version: Literal['reduction.authority.v1'] = 'reduction.authority.v1'
    actor_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    permission: Literal['buyer_request', 'assigned_work']
    current: StrictBool
    checked_at: AwareDatetime
    valid_until: AwareDatetime
    commitment_id: UUID
    accepted_scope: StrictBool
    custody_current: StrictBool
    payment_state: Literal['paid_held', 'pending', 'unpaid']
    fit_confirmed: StrictBool
    incident_open: StrictBool
    currency: Literal['USD']
    total_minor: StrictInt = Field(ge=0, le=999999999999)
    responsible_actor_id: UUID
    next_review_at: AwareDatetime
    choices: list[Choice] = Field(max_length=100)
    removable_link_ids: list[UUID] = Field(max_length=100)
    buyer_owned_link_ids: list[UUID] = Field(max_length=100)
    authorized_recipient_ids: list[UUID] = Field(max_length=100)
    accepted_straps: list[AcceptedStrap] = Field(default_factory=list, max_length=100)
    accepted_exceptions: list[ReturnException] = Field(default_factory=list, max_length=100)


class Result(Command):
    schema_version: Literal['reduction.result.v1'] = 'reduction.result.v1'
    actor_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    commitment_id: UUID
    state: Literal['requested', 'unresolved', 'recorded']
    revision: StrictInt = Field(ge=1)
    accepted_exception_basis: Literal['supplier_exchange', 'non_buyer_owned'] | None
    removed_count: StrictInt = Field(ge=0, le=100)
    returned_count: StrictInt = Field(ge=0, le=100)
    pending_reason: Literal['fit_or_parts'] | None
    next_actor: UUID
    next_review_at: AwareDatetime
    recorded_at: AwareDatetime
    currency: Literal['USD']
    total_minor: StrictInt = Field(ge=0, le=999999999999)
    handover_authorized: Literal[False] = False
