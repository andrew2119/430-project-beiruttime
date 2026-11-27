"""Receiving-business designation and its bounded reservation projection."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictInt, model_validator
from .staff import Closed, MaintenanceFenceProof


class Designation(Closed):
    operation_id: UUID
    request_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=1)
    expected_revision: StrictInt = Field(ge=0)
    responsible_operator_id: UUID | None


class DesignationReceipt(Designation):
    request_id: UUID
    organization_id: UUID
    actor_id: UUID
    revision: StrictInt = Field(ge=1)


class CurrentDesignation(Closed):
    request_id: UUID
    organization_id: UUID
    request_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=1)
    revision: StrictInt = Field(ge=0)
    responsible_operator_id: UUID | None


class DestinationBinding(Closed):
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    brand_id: UUID
    organization_id: UUID
    watch_id: UUID
    intervention: Literal['limited_maintenance','overhaul_assessment']
    assessor_id: UUID
    assignment_revision: StrictInt = Field(ge=1)


class DestinationFence(Closed):
    schema_version: Literal[1]
    hold_until: AwareDatetime
    binding: DestinationBinding


class Destination(Closed):
    seller_id: UUID
    responsible_operator_id: UUID
    seller_type: Literal['brand','dealer']


class DestinationProof(MaintenanceFenceProof):
    result: Destination


class DestinationQualification(Closed):
    purpose: Literal['maintenance_assessment_destination'] = 'maintenance_assessment_destination'
    organization_id: UUID
    brand_id: UUID
    intervention: Literal['limited_maintenance','overhaul_assessment']
    assessor_id: UUID
    responsible_operator_id: UUID | None
    designator_id: UUID | None
    session_id: str | None = Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def exact_purpose(self):
        if ((self.designator_id is None)!=(self.session_id is None)
                or (self.designator_id is None and self.responsible_operator_id is None)):
            raise ValueError('maintenance_destination_scope')
        return self


class DestinationQualificationFence(Closed):
    schema_version: Literal[1]
    hold_until: AwareDatetime
    binding: DestinationQualification


class QualifiedDestination(Closed):
    seller_id: UUID
    seller_type: Literal['brand','dealer']


class DestinationQualificationProof(MaintenanceFenceProof):
    result: QualifiedDestination
