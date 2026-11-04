"""Private technical-intake commands and the Orders receipt dependency contract."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, field_validator
from bt_contracts_core.models import Contract


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

    @field_validator('serial','reference','movement','received_condition','reported_issue')
    @classmethod
    def meaningful_text(cls,value):
        if not value.strip():
            raise ValueError('A meaningful value is required')
        return value.strip()


class Receipt(Contract):
    id: UUID
    order_id: UUID
    organization_id: UUID
    received_at: AwareDatetime
    revision: StrictInt = Field(ge=1)
    valid: Literal[True]

    @field_validator('valid',mode='before')
    @classmethod
    def actual_boolean_proof(cls,value):
        if value is not True:
            raise ValueError('A current valid receipt is required')
        return value


class EvidenceUpload(Contract):
    kind: Literal['condition_photo','prior_owner_record']
    media_type: Literal['image/jpeg','image/png','image/webp','application/pdf']
    content_base64: str = Field(min_length=4,max_length=349528)


class IntakeEvent(Contract):
    record_id: UUID
    order_id: UUID
    organization_id: UUID
    state: Literal['awaiting_intake','received']
    revision: int = Field(ge=1)
    custody_receipt_id: UUID | None
