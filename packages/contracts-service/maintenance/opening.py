"""Scoped maintenance opening preference and physical intake acknowledgement."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

from bt_contracts.service.intake.current import CurrentCustodyReceipt


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Preference(Closed):
    operation_id: UUID
    request_revision: StrictInt = Field(ge=1)
    expected_revision: StrictInt = Field(ge=0)
    opening_permitted: StrictBool
    no_polish: StrictBool


class PreferenceReceipt(Preference):
    request_id: UUID
    buyer_id: UUID
    organization_id: UUID
    watch_id: UUID
    revision: StrictInt = Field(ge=1)
    recorded_at: AwareDatetime


class AcknowledgementBinding(Closed):
    request_revision: StrictInt = Field(ge=1)
    consent_revision: StrictInt = Field(ge=1)
    assignment_revision: StrictInt = Field(ge=1)
    order_id: UUID
    receipt_id: UUID
    receipt_revision: StrictInt = Field(ge=1)
    fee_acceptance_operation_id: UUID
    offer_id: UUID
    offer_revision: StrictInt = Field(ge=1)


class Acknowledge(AcknowledgementBinding):
    operation_id: UUID


class AcceptedFee(Closed):
    operation_id: UUID
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    organization_id: UUID
    offer_id: UUID
    offer_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    amount_minor: StrictInt = Field(ge=0)
    currency: Literal['USD']
    state: Literal['accepted']
    decided_at: AwareDatetime


class OpeningAcknowledgement(Acknowledge):
    request_id: UUID
    actor_id: UUID
    buyer_id: UUID
    organization_id: UUID
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)
    customer_opening_permission: StrictBool
    customer_no_polish_acknowledged: StrictBool
    no_polish: StrictBool
    accepted_assessment_fee: StrictBool
    accepted_fee_minor: StrictInt = Field(ge=0)
    policy_revision: StrictInt = Field(ge=1)
    received_at: AwareDatetime


class AssessmentFeeBinding(Closed):
    order_id: UUID
    request_id: UUID
    request_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    organization_id: UUID
    watch_id: UUID
    receipt_id: UUID
    operation_id: UUID
    offer_id: UUID
    offer_revision: StrictInt = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    amount_minor: StrictInt = Field(ge=0)
    currency: Literal['USD']


class OpeningFenceBinding(Closed):
    operation_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    custody: CurrentCustodyReceipt
    retained_fee: AssessmentFeeBinding


class OpeningFenceRequest(Closed):
    schema_version: Literal[1]
    hold_until: AwareDatetime
    binding: OpeningFenceBinding


class OpeningFenceResult(Closed):
    binding_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    held_until: AwareDatetime


class IntakeOpeningReview(Closed):
    request_id: UUID
    organization_id: UUID
    actor_id: UUID
    watch_id: UUID
    received_at: AwareDatetime
    opening_permitted: StrictBool
    no_polish: StrictBool
    binding: AcknowledgementBinding
    fee: AcceptedFee
    acknowledged: StrictBool
