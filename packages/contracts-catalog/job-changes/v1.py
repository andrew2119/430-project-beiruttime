"""Versioned private material-change contracts. Amounts are integer USD cents."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re


class Rejected(ValueError):
    pass


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value):
        raise Rejected('invalid_reference')
    return value


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() != timezone.utc.utcoffset(result):
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise Rejected('invalid_utc') from None


@dataclass(frozen=True)
class Change:
    operation_id: str
    subject_id: str
    watch_id: str
    actor_id: str
    organization_id: str
    responsible_operator_id: str
    expected_revision: int
    order_id: str
    source_scope_id: str
    proposed_scope_id: str
    retained_quote_id: str
    retained_quote_revision: int
    reason: str
    schema_version: str = 'job-changes.v1'

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key.endswith('_id'):
                identifier(value)
        if self.schema_version != 'job-changes.v1':
            raise Rejected('invalid_version')
        for value in (self.expected_revision, self.retained_quote_revision):
            if type(value) is not int or not 1 <= value <= 2147483647:
                raise Rejected('invalid_revision')
        if not isinstance(self.reason, str) or not 3 <= len(self.reason.strip()) <= 1000:
            raise Rejected('invalid_reason')
        if self.source_scope_id == self.proposed_scope_id:
            raise Rejected('unchanged_scope')


@dataclass(frozen=True)
class Approval:
    operation_id: str
    scope_id: str
    scope_revision: int
    assessment_id: str
    assessment_revision: int
    quote_id: str
    quote_revision: int
    consent_revision: int
    eligibility_revision: int
    policy_revision: int
    approval_revision: int
    acceptance_revision: int
    payment_revision: int
    total_minor: int
    business_fee_minor: int
    assessor_id: str
    approver_id: str
    quality_reviewer_id: str
    eligibility_reviewer_id: str
    accepted_at: str
    currency: str = 'USD'

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key.endswith('_id'):
                identifier(value)
            if key.endswith('_revision') and (type(value) is not int or not 1 <= value <= 2147483647):
                raise Rejected('invalid_revision')
        if self.currency != 'USD' or type(self.total_minor) is not int or not 0 < self.total_minor <= 9007199254740991:
            raise Rejected('invalid_money')
        if type(self.business_fee_minor) is not int or self.business_fee_minor != (self.total_minor * 5 + 50) // 100:
            raise Rejected('invalid_fee')
        if len({self.assessor_id, self.approver_id, self.quality_reviewer_id, self.eligibility_reviewer_id}) != 4:
            raise Rejected('independence_required')
        instant(self.accepted_at)
