"""Private technical-intake commands and the Orders receipt dependency contract."""
from typing import Literal
from uuid import UUID
from pydantic import Field, StrictBool, StrictInt, field_validator
from bt_contracts_core.models import Contract


class OpeningAcceptance(Contract):
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    accepted_terms_revision: StrictInt = Field(ge=1)
    consent_revision: StrictInt = Field(ge=1)


class AssessmentCustody(Contract):
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    receipt_id: UUID
    receipt_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)


class Intake(Contract):
    order_id: UUID
    custody_receipt_id: UUID | None = None
    serial: str = Field(min_length=1,max_length=160)
    reference: str = Field(min_length=1,max_length=160)
    movement: str = Field(min_length=1,max_length=160)
    received_condition: str = Field(min_length=1,max_length=2000)
    accessories: str = Field(max_length=2000)
    reported_issue: str = Field(min_length=1,max_length=2000)
    assessed_issue: str = Field(max_length=2000)
    diagnostic_opening_permission: StrictBool
    no_polish_acknowledged: StrictBool
    fee_acknowledged: StrictBool
    fee_minor: StrictInt = Field(ge=0,le=999999999999)
    currency: Literal['USD','LBP']
    opening_acceptance: OpeningAcceptance | None = None
    reviewed_assessment_custody: AssessmentCustody | None = None
    reviewed_receipt_revision: AssessmentCustody | None = None

    @field_validator('serial','reference','movement','received_condition','reported_issue')
    @classmethod
    def meaningful_text(cls,value):
        if not value.strip():
            raise ValueError('A meaningful value is required')
        return value.strip()


class EvidenceUpload(Contract):
    safe_photo_declared: StrictBool = False
    kind: Literal['condition_photo','prior_owner_record']
    media_type: Literal['image/jpeg','image/png','image/webp','application/pdf']
    content_base64: str = Field(min_length=4,max_length=349528)


class IntakeOperationCommand(Contract):
    action: Literal['lookup', 'close']
    operation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,128}$')


class IntakeOperationReceipt(Contract):
    operation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,128}$')
    organization_id: UUID
    record_id: UUID
    order_id: UUID
    revision: StrictInt = Field(ge=1)
    kind: Literal['save', 'evidence']
    maintenance_request_id: UUID | None = None
