"""Current assigned-record and custody bindings for diagnostic opening."""
from uuid import UUID
from typing import Literal
from pydantic import AwareDatetime, StrictBool, StrictInt, Field
from bt_contracts_core.models import Contract
from .intake_command import OpeningAcceptance
from .v1 import Receipt

class CurrentCustodyReceipt(Receipt):
    actor_id: UUID
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)
    current_watch_id: UUID
    current_watch_revision: StrictInt = Field(ge=1)
    current_incident_revision: StrictInt = Field(ge=0)


class RepairCustodyTransition(Contract):
    actor_id: UUID
    organization_id: UUID
    assessment_order_id: UUID
    repair_order_id: UUID
    watch_id: UUID
    assessment_receipt_id: UUID
    assessment_receipt_revision: StrictInt = Field(ge=1)
    assessment_watch_revision: StrictInt = Field(ge=1)
    assessment_incident_revision: StrictInt = Field(ge=0)
    repair_watch_revision: StrictInt = Field(ge=1)
    current_incident_revision: StrictInt = Field(ge=0)
    current: StrictBool
    work_hold: StrictBool


class OpeningAuthority(OpeningAcceptance):
    actor_id: UUID
    organization_id: UUID
    order_id: UUID
    receipt_id: UUID
    receipt_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)
    current_watch_id: UUID | None = None
    current_watch_revision: StrictInt | None = Field(default=None, ge=1)
    current_incident_revision: StrictInt | None = Field(default=None, ge=0)
    received_at: AwareDatetime
    current: StrictBool
    assigned: StrictBool
    permission: StrictBool
    customer_opening_permission: StrictBool
    accepted_assessment_fee: StrictBool
    customer_no_polish_acknowledged: StrictBool
    accepted_fee_minor: StrictInt = Field(ge=0,le=999999999999)
    currency: Literal['USD']
    maintenance_request_id: UUID | None = None
    reservation_input_watch_revision: StrictInt | None = Field(default=None, ge=1)

class RecordAccess(Contract):
    actor_id: UUID
    organization_id: UUID
    order_id: UUID
    permission: Literal['read', 'write', 'assess']
    assignment_revision: StrictInt = Field(ge=1)
    allowed: StrictBool

class RecordListAccess(Contract):
    actor_id: UUID
    organization_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    order_ids: list[UUID] = Field(max_length=10000)

class PaidReadiness(Contract):
    buyer_id: UUID
    order_id: UUID
    order_kind: Literal['job']
    watch_id: UUID
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    currency: Literal['USD']
    total_minor: StrictInt = Field(ge=0, le=999999999999)
    payment_operation_id: UUID
    payment_revision: StrictInt = Field(ge=1)
    state: Literal['paid_held', 'pending', 'unpaid']
