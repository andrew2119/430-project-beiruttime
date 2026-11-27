"""Versioned, extensible assessed scope. Reported symptoms are never line evidence."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, StrictBool, model_validator
from bt_contracts_core.models import Contract

class CaseLine(Contract):
    line_id: UUID
    kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]*$")
    description: str = Field(min_length=1, max_length=2000)
    required: StrictBool
    amount_minor: StrictInt = Field(ge=0, le=9_000_000_000_000)
    currency: Literal['USD'] = 'USD'
    assessment_id: UUID
    assessment_revision: StrictInt = Field(ge=1)

class Scope(Contract):
    schema_version: Literal['service.case-lines.v1'] = 'service.case-lines.v1'
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    revision: StrictInt = Field(ge=1)
    lines: list[CaseLine] = Field(min_length=1, max_length=100)
    accepted_line_ids: list[UUID] = Field(max_length=100)

    @model_validator(mode='after')
    def exact_selection(self):
        ids = [line.line_id for line in self.lines]
        chosen = self.accepted_line_ids
        if len(ids) != len(set(ids)) or len(chosen) != len(set(chosen)) or not set(chosen) <= set(ids):
            raise ValueError('Invalid line selection')
        return self

    def accepted_total(self):
        if any(line.required and line.line_id not in self.accepted_line_ids for line in self.lines):
            raise ValueError('Every mandatory line requires explicit acceptance')
        return sum(line.amount_minor for line in self.lines if line.line_id in self.accepted_line_ids)

def accepted_payable(quote, line_subtotal: int) -> int:
    """Verify the acknowledged USD payable against the selected work and fee."""
    decision = quote['decision']
    fee = quote['assessment_fee_minor']
    amounts = decision['amounts']
    payable = amounts['payable_minor']
    if (type(line_subtotal) is not int or line_subtotal < 0
            or type(fee) is not int or fee < 0
            or type(amounts['assessment_fee_minor']) is not int
            or amounts['assessment_fee_minor'] != fee
            or (fee and decision['accepted_fee_lines']['assessment'] is not True)
            or type(payable) is not int or payable <= 0
            or payable != line_subtotal + fee):
        raise ValueError('invalid_accepted_payable')
    return payable


class ScopeReceipt(Contract):
    schema_version: Literal['service.case-lines.v1'] = 'service.case-lines.v1'
    operation_id: UUID
    actor_id: UUID
    subject_id: UUID
    organization_id: UUID
    watch_id: UUID
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    expected_revision: StrictInt = Field(ge=0)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    state: Literal['accepted','denied','stale','pending']
    revision: StrictInt = Field(ge=0)
    pending_reason: str | None = None
    next_actor: Literal['customer','business','support']
    next_review_at: AwareDatetime | None = None
    case_id: UUID | None = None
    assessment_id: UUID | None = None
    assessment_revision: StrictInt | None = Field(default=None, ge=1)

OPERATIONS = {
    'current': ('GET', '/v1/case-lines/{request_id}'),
    'accept': ('POST', '/v1/case-lines/{request_id}/acceptance'),
    'lookup': ('GET', '/v1/case-lines/operations/{operation_id}'),
}
