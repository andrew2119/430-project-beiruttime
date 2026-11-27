"""Current assigned-record and custody bindings for diagnostic opening."""
from uuid import UUID
from typing import Literal
from pydantic import AwareDatetime, StrictBool, StrictInt, Field
from bt_contracts_core.models import Contract

class OpeningAuthority(Contract):
    actor_id: UUID
    organization_id: UUID
    order_id: UUID
    receipt_id: UUID
    receipt_revision: StrictInt = Field(ge=1)
    watch_id: UUID
    watch_revision: StrictInt = Field(ge=1)
    incident_revision: StrictInt = Field(ge=0)
    received_at: AwareDatetime
    current: StrictBool
    assigned: StrictBool
    permission: StrictBool
    customer_opening_permission: StrictBool
    accepted_assessment_fee: StrictBool
    customer_no_polish_acknowledged: StrictBool
    consent_revision: StrictInt = Field(ge=1)
    accepted_terms_revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    accepted_fee_minor: StrictInt = Field(ge=0,le=999999999999)
    currency: Literal['USD']
    maintenance_request_id: UUID | None = None
    reservation_input_watch_revision: StrictInt | None = Field(default=None, ge=1)

class RecordAccess(Contract):
    actor_id: UUID
    organization_id: UUID
    order_id: UUID
    permission: Literal['read','write']
    assignment_revision: StrictInt = Field(ge=1)
    allowed: StrictBool

class RecordListAccess(Contract):
    actor_id: UUID
    organization_id: UUID
    assignment_revision: StrictInt = Field(ge=1)
    order_ids: list[UUID] = Field(max_length=10000)
