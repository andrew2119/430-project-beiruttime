"""Private role assignments and short-lived authority fences."""

from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, model_validator

Revision = StrictInt
Kind = Literal['customization', 'repair']


class Wire(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)


class Roles(Wire):
    assessor_id: UUID
    approver_id: UUID
    quality_reviewer_id: UUID
    recovery_operator_id: UUID

    @model_validator(mode='after')
    def independent(self):
        if len({self.assessor_id, self.approver_id, self.quality_reviewer_id}) != 3:
            raise ValueError('independent_roles_required')
        return self


class Assignment(Wire):
    operation_id: UUID
    kind: Kind
    expected_revision: Revision = Field(ge=0, lt=2147483647)
    source_revision: Revision = Field(ge=1, le=2147483647)
    buyer_id: UUID
    organization_id: UUID
    watch_id: UUID
    roles: Roles
    reason: str = Field(min_length=10, max_length=500)

    @model_validator(mode='after')
    def excludes_buyer(self):
        if self.buyer_id in self.roles.model_dump().values():
            raise ValueError('independent_roles_required')
        return self


class EligibilityBinding(Wire):
    request_id: UUID
    request_revision: Revision = Field(ge=1)
    buyer_id: UUID
    brand_id: UUID
    watch_id: UUID
    watch_revision: Revision = Field(ge=1)
    request_binding_revision: Revision = Field(ge=1)
    assessment_id: UUID
    assessment_revision: Revision = Field(ge=1)
    assessment_assignment_revision: Revision = Field(ge=1)
    approver_id: UUID


class Deadline(Wire):
    schema_version: Literal[1]
    hold_until: AwareDatetime

    @model_validator(mode='after')
    def utc_deadline(self):
        if self.hold_until.utcoffset() != timedelta(0):
            raise ValueError('utc_deadline_required')
        return self


class EligibilityFence(Deadline):
    binding: EligibilityBinding


class FenceReceipt(Wire):
    binding_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    held_until: AwareDatetime
