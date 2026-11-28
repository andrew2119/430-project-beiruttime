"""Maintenance assignment, precharge receipt and operation recovery contracts."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from bt_contracts.service.intake.current import CurrentCustodyReceipt


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StaffGrant(Closed):
    actor_id: UUID
    organization_id: UUID
    can_route: StrictBool
    can_assess: StrictBool


class Assignment(Closed):
    operation_id: UUID
    assessor_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    request_revision: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000, pattern=r'\S')


class PrechargeCustody(CurrentCustodyReceipt):
    request_id: UUID
    title_holder_id: UUID
    brand_id: UUID
    precharge: Literal[True]

    @field_validator('precharge', mode='before')
    @classmethod
    def literal_precharge(cls, value):
        if value is not True:
            raise ValueError('precharge_custody_required')
        return value


class Confirmation(Closed):
    operation_id: UUID
    order_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    request_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    custody_receipt_id: UUID
    custody_receipt_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)
    decision: Literal['confirmed', 'rejected']
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def rejection_reason(self):
        if self.decision == 'rejected' and (not self.reason or not self.reason.strip()):
            raise ValueError('rejection_reason_required')
        return self


class AssignmentReceipt(Closed):
    operation_id: UUID
    request_id: UUID
    organization_id: UUID
    actor_id: UUID
    assessor_id: UUID
    revision: StrictInt = Field(ge=1)
    request_revision: StrictInt = Field(ge=1)


class PrechargeFenceBinding(Closed):
    operation_id: UUID
    request_id: UUID
    actor_id: UUID
    organization_id: UUID
    request_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=1)
    title_holder_id: UUID
    brand_id: UUID
    order_id: UUID
    custody_receipt_id: UUID
    custody_receipt_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)
    decision: Literal['confirmed', 'rejected']


class MaintenanceFenceProof(Closed):
    binding_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    held_until: AwareDatetime


class OrdersPrechargeBinding(Closed):
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    organization_id: UUID
    brand_id: UUID
    order_id: UUID
    custody_receipt_id: UUID
    custody_receipt_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)
    operation_id: UUID
    decision: Literal['confirmed', 'rejected']


class OrdersPrechargeFence(Closed):
    schema_version: Literal[1]
    hold_until: AwareDatetime
    binding: OrdersPrechargeBinding


class IntakeGrantBinding(Closed):
    actor_id: UUID
    organization_id: UUID
    brand_id: UUID


class IntakeGrantFence(Closed):
    schema_version: Literal[1]
    hold_until: AwareDatetime
    binding: IntakeGrantBinding


class ConfirmationReceipt(Closed):
    operation_id: UUID
    order_id: UUID
    request_id: UUID
    organization_id: UUID
    actor_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    request_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    custody_receipt_id: UUID
    custody_receipt_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)
    state: Literal['confirmed', 'rejected']


class HistoricalOwner(Closed):
    actor_id: UUID
    watch_id: UUID
    title_holder_id: UUID | None
    owned: StrictBool


class RoutingAssignment(Closed):
    request_id: UUID
    organization_id: UUID
    request_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=0)
    assessor_id: UUID | None


STAFF_OPERATIONS = {
    'current_assignment': ('GET', '/v1/maintenance/requests/{request_id}/assignment'),
    'assign': ('POST', '/v1/maintenance/requests/{request_id}/assignment'),
    'confirm': ('POST', '/v1/maintenance/requests/{request_id}/watch-confirmation'),
    'lookup': ('GET', '/v1/maintenance/requests/{request_id}/staff-operations/{operation_id}'),
}
