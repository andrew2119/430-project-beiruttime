"""Private request contract; submission confers neither custody nor work authority."""
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, ConfigDict, field_validator, model_validator
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
    model_config = ConfigDict(json_schema_extra={
        'if': {'properties': {'state': {'const': 'submitted'}}, 'required': ['state']},
        'then': {'properties': {'revision': {'const': 1}}},
        'else': {'properties': {'revision': {'const': 0}}},
    })


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
    brand_id: UUID
    intervention: Literal['limited_maintenance', 'overhaul_assessment']
    state: Literal['submitted','denied','stale','pending']
    revision: StrictInt = Field(ge=0)
    pending_reason: str | None = None
    next_actor: Literal['customer','business','support']
    next_review_at: AwareDatetime | None = None

    @model_validator(mode='after')
    def revision_matches_state(self):
        expected = 1 if self.state == 'submitted' else 0
        if self.revision != expected:
            raise ValueError('Receipt revision does not match its state')
        return self

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

class PhotoBinding(Contract):
    operation_id: UUID
    request_operation_id: UUID
    watch_id: UUID
    organization_id: UUID
    brand_id: UUID
    intervention: Literal['limited_maintenance', 'overhaul_assessment']
    watch_revision: StrictInt = Field(ge=1)
    capability_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)


class PhotoReceipt(PhotoBinding):
    actor_id: UUID
    subject_id: UUID
    photo_ref: UUID
    revision: Literal[1]


class Photo(PhotoBinding):
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


class AssessmentAccess(Contract):
    request_id: UUID
    actor_id: UUID
    organization_id: UUID
    watch_id: UUID
    brand_id: UUID
    intervention: Literal['limited_maintenance', 'overhaul_assessment']
    request_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=1)
    capability_revision: StrictInt = Field(ge=1)
    allowed: StrictBool


class AssessmentRequest(Contract):
    request_id: UUID
    revision: StrictInt = Field(ge=1)
    assessor_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    brand_id: UUID
    intervention: Literal['limited_maintenance', 'overhaul_assessment']
    reported_symptoms: str = Field(min_length=1, max_length=2000)
    known_modifications: str = Field(max_length=2000)
    limited_assessment_permission: Literal[True]
    photo_refs: list[UUID] = Field(max_length=10)
    submitted_at: AwareDatetime


class AssessmentPhoto(Contract):
    photo_ref: UUID
    media_type: Literal['image/jpeg', 'image/png', 'image/webp']
    content_base64: str = Field(min_length=4, max_length=349528)


UNATTACHED_PHOTO_RETENTION_DAYS = 7


def unsubmitted_photo_expires_at(uploaded_at: datetime) -> datetime:
    """Compute the deadline from the first durable server-side upload instant."""
    if uploaded_at.utcoffset() != timedelta(0):
        raise ValueError('Upload time must be UTC')
    return uploaded_at + timedelta(days=UNATTACHED_PHOTO_RETENTION_DAYS)


def unsubmitted_photo_is_current(uploaded_at: datetime, now: datetime) -> bool:
    if now.utcoffset() != timedelta(0):
        raise ValueError('Current time must be UTC')
    return uploaded_at <= now < unsubmitted_photo_expires_at(uploaded_at)


OPERATIONS.update({
    'close': ('DELETE', '/v1/maintenance/operations/{operation_id}'),
    'assessment': ('GET', '/v1/maintenance/requests/{request_id}'),
    'assessment_photo': ('GET', '/v1/maintenance/requests/{request_id}/photos/{photo_ref}'),
})


class AssessmentQueueAccess(Contract):
    actor_id: UUID
    organization_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    request_ids: list[UUID] = Field(max_length=10000)
    routing_allowed: StrictBool = False


class AssessmentQueueItem(Contract):
    request_id: UUID
    delivered_at: AwareDatetime


class AssessmentQueue(Contract):
    items: list[AssessmentQueueItem] = Field(max_length=50)
    total: StrictInt = Field(ge=0)
    next_offset: StrictInt | None = Field(ge=0)


OPERATIONS['assessment_queue'] = ('GET', '/v1/maintenance/assessment-inbox')


class DeliveryRetry(Contract):
    held_at: AwareDatetime


class DeliveryRecoveryCommand(DeliveryRetry):
    action: Literal['acknowledge', 'retry', 'review_escalation'] = 'retry'


class DeliveryHold(DeliveryRetry):
    operation_id: UUID
    operator_id: UUID
    next_review_at: AwareDatetime
    escalate_at: AwareDatetime
    escalated_at: AwareDatetime | None = None
    retry_in_progress: StrictBool = False
    escalation_reviewed_at: AwareDatetime | None = None
    first_response_at: AwareDatetime | None = None
    first_response_overdue: StrictBool = False
    next_action: Literal['review_and_retry_delivery', 'respond_to_overdue_delivery', 'resolve_escalated_delivery',
                         'review_active_escalation', 'review_delivered_escalation',
                         'monitor_escalated_retry'] = 'review_and_retry_delivery'


OPERATIONS.update({
    'delivery_holds': ('GET', '/v1/maintenance/delivery-recovery'),
    'retry_delivery': ('POST', '/v1/maintenance/delivery-recovery/{operation_id}'),
})
