"""Private request contract; submission confers neither custody nor work authority."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, field_validator
from bt_contracts_core.models import Contract

class Request(Contract):
    schema_version: Literal['service.maintenance.v1'] = 'service.maintenance.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    watch_revision: StrictInt = Field(ge=1)
    capability_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    brand_id: UUID
    intervention: Literal['limited_maintenance','overhaul_assessment']
    reported_symptoms: str = Field(min_length=1,max_length=2000)
    known_modifications: str = Field(max_length=2000)
    photo_refs: list[UUID] = Field(max_length=10)
    limited_assessment_permission: StrictBool

    @field_validator('reported_symptoms')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Reported symptoms are required')
        return value

class Result(Contract):
    schema_version: Literal['service.maintenance.v1'] = 'service.maintenance.v1'
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    request_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    capability_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    state: Literal['submitted','denied','stale','pending']
    revision: StrictInt = Field(ge=0)
    pending_reason: str | None = None
    next_actor: Literal['customer','business','support']
    next_review_at: AwareDatetime | None = None

OPERATIONS = {
    'submit': ('POST', '/v1/maintenance/requests'),
    'lookup': ('GET', '/v1/maintenance/operations/{operation_id}'),
    'context': ('GET', '/v1/maintenance/context/{watch_id}'),
    'photo': ('POST', '/v1/maintenance/photos'),
}

class Destination(Contract):
    organization_id: UUID
    brand_id: UUID
    capability_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=200)
    interventions: list[Literal['limited_maintenance','overhaul_assessment']] = Field(min_length=1,max_length=2)

class Context(Contract):
    actor_id: UUID
    subject_id: UUID
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    destinations: list[Destination] = Field(max_length=100)

class Photo(Contract):
    operation_id: UUID
    request_operation_id: UUID
    watch_id: UUID
    organization_id: UUID
    media_type: Literal['image/jpeg','image/png','image/webp']
    content_base64: str = Field(min_length=4,max_length=349528)
    safe_photo_declared: StrictBool

class AdmissionAuthority(Contract):
    actor_id: UUID
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    brand_id: UUID
    operation_id: UUID
    intervention: Literal['limited_maintenance','overhaul_assessment']
    watch_revision: StrictInt = Field(ge=1)
    capability_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    identity_current: StrictBool
    watch_owned: StrictBool
    business_active: StrictBool
    assessment_supported: StrictBool
    commitment_available: StrictBool


class RequestAuthority(AdmissionAuthority):
    private_refs_current: StrictBool
