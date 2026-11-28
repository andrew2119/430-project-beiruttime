"""Private minimal references, never evidence or execution authority."""
from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Source = Literal['trust', 'orders', 'service-operations']
Outcome = Literal['accepted', 'denied', 'pending', 'cancelled']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class AuditQuery(Contract):
    schema_version: Literal['audit-references.v1'] = 'audit-references.v1'
    operation_id: UUID
    organization_id: UUID
    actor_id: UUID | None = None
    resource_id: UUID | None = None
    outcome: Outcome | None = None
    after: AwareDatetime
    before: AwareDatetime
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=20, ge=1, le=50)
    expected_revision: int | None = Field(default=None, ge=1, le=9007199254740991)

    @field_validator('after', 'before')
    @classmethod
    def utc(cls, value):
        if value.utcoffset() != timedelta(0):
            raise ValueError('UTC required')
        return value

    @model_validator(mode='after')
    def bounded(self):
        if not timedelta(0) < self.before - self.after <= timedelta(days=31):
            raise ValueError('Use a positive interval of at most 31 days')
        return self


class AuditReference(Contract):
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID | None
    actor_id: UUID
    organization_id: UUID
    expected_revision: int = Field(ge=0, le=9007199254740991)
    state: Outcome
    revision: int = Field(ge=1, le=9007199254740991)
    occurred_at: AwareDatetime
    reason_code: Literal['scope_changed', 'permission_changed', 'record_changed', 'review_recorded', 'awaiting_owner']
    reason_reference: UUID
    pending_reason: Literal['owner_pending'] | None
    next_actor: UUID | None
    next_review_at: AwareDatetime | None

    @field_validator('occurred_at', 'next_review_at')
    @classmethod
    def utc(cls, value):
        if value is not None and value.utcoffset() != timedelta(0):
            raise ValueError('UTC required')
        return value

    @model_validator(mode='after')
    def pending(self):
        if self.state == 'pending' and (self.pending_reason is None or self.next_actor is None or self.next_review_at is None):
            raise ValueError('Pending references need a responsible person and next review')
        return self


class OwnerPage(Contract):
    schema_version: Literal['audit-references.v1']
    operation_id: UUID
    organization_id: UUID
    reader_id: UUID
    query: AuditQuery
    revision: int = Field(ge=1, le=9007199254740991)
    items: list[AuditReference] = Field(max_length=50)
    total: int = Field(ge=0, le=9007199254740991)
    next_offset: int | None = Field(ge=0, le=10000)

    @model_validator(mode='after')
    def page(self):
        q = self.query
        if self.operation_id != q.operation_id or self.organization_id != q.organization_id:
            raise ValueError('Query binding mismatch')
        if q.expected_revision is not None and q.expected_revision != self.revision:
            raise ValueError('Revision mismatch')
        if len(self.items) != min(q.limit, max(0, self.total - q.offset)):
            raise ValueError('Incomplete page')
        following = q.offset + len(self.items)
        expected = following if following < self.total and following <= 10000 else None
        if self.next_offset != expected or len({r.operation_id for r in self.items}) != len(self.items):
            raise ValueError('Invalid pagination or duplicate reference')
        for r in self.items:
            if (r.organization_id != q.organization_id or not q.after <= r.occurred_at < q.before
                    or q.actor_id is not None and r.actor_id != q.actor_id
                    or q.resource_id is not None and r.subject_id != q.resource_id
                    or q.outcome is not None and r.state != q.outcome):
                raise ValueError('Record scope mismatch')
        if self.items != sorted(self.items, key=lambda r: (r.occurred_at, str(r.operation_id)), reverse=True):
            raise ValueError('Unstable order')
        return self
