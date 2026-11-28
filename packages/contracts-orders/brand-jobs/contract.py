"""Versioned private authorization boundary. Facts come from current providers."""
from dataclasses import dataclass
from typing import Literal

VERSION = 'orders.brand-jobs.v1'
OPERATIONS = {
    'authorize': ('POST', '/internal/v1/brand-jobs'),
    'lookup': ('GET', '/internal/v1/brand-jobs/operations/{operation_id}'),
    'service': ('POST', '/internal/v1/service-jobs/paid-scope'),
}

@dataclass(frozen=True)
class Command:
    operation_id: str
    subject_id: str
    watch_id: str
    actor_id: str
    organization_id: str
    expected_revision: int
    quote_id: str
    quote_revision: int
    policy_revision: int
    kind: Literal['customization', 'repair'] = 'customization'

    service_acceptance_id: str | None = None
    service_order_id: str | None = None
    service_total_minor: int | None = None
    service_payment_operation_id: str | None = None
    service_payment_revision: int | None = None

    def __post_init__(self):
        for value in (self.operation_id, self.subject_id, self.watch_id, self.actor_id,
                      self.organization_id, self.quote_id):
            if not isinstance(value, str) or not 1 <= len(value) <= 100:
                raise ValueError('invalid_reference')
        for value in (self.expected_revision, self.quote_revision, self.policy_revision):
            if type(value) is not int or value < 1:
                raise ValueError('invalid_revision')
        for value in (self.service_acceptance_id, self.service_order_id, self.service_payment_operation_id):
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 100):
                raise ValueError('invalid_reference')
        for value in (self.service_total_minor, self.service_payment_revision):
            if value is not None and (type(value) is not int or not 1 <= value <= 9007199254740991):
                raise ValueError('invalid_revision')
        if self.kind not in ('customization', 'repair'):
            raise ValueError('invalid_kind')

@dataclass(frozen=True)
class Scope:
    buyer_id: str
    watch_id: str
    organization_id: str
    revision: int
    quote_id: str
    quote_revision: int
    policy_revision: int
    currency: str
    total_minor: int
    business_fee_minor: int
    accepted: bool
    authority_current: bool
    allocation_current: bool
    paid_held: bool
    approval_current: bool
    grant_current: bool
    consent_current: bool
    assignee_id: str
    assignee_qualified: bool
    assessor_id: str
    approver_id: str
    quality_reviewer_id: str
    eligibility_reviewer_id: str
    source_revision: int
    order_id: str
    service_acceptance_id: str | None = None
    payment_operation_id: str | None = None
    payment_revision: int | None = None

@dataclass(frozen=True)
class ServiceAcceptance:
    acceptance_id: str
    revision: int
    buyer_id: str
    organization_id: str
    watch_id: str
    quote_id: str
    quote_revision: int
    total_minor: int
    accepted: bool

@dataclass(frozen=True)
class PaidServiceScope:
    buyer_id: str
    order_id: str
    order_kind: str
    watch_id: str
    quote_id: str
    quote_revision: int
    currency: str
    total_minor: int
    payment_operation_id: str
    payment_revision: int
    state: str


@dataclass(frozen=True)
class RecoveryAssignment:
    operator_id: str
    next_action: str
    escalation_actor_id: str
    opened_at: str
    next_review_at: str
    escalate_at: str
