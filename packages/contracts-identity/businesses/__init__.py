"""Identity Businesses V1 public transport contracts, never private evidence."""
from typing import Literal
from uuid import UUID
from pydantic import Field
from bt_contracts_core.models import Contract


class OfficialBusiness(Contract):
    id: UUID
    public_name: str = Field(min_length=2,max_length=120)
    kind: Literal['dealer','brand']
    capabilities: list[Literal['sales','customization','servicing']]
    state: Literal['active','revoked']
    revision: int = Field(ge=1)
    sample: bool
    platform_onboarded: bool
    authenticated_business: bool
    independent_watch_authentication_required: Literal[False]=False


class Membership(Contract):
    id: UUID
    business_id: UUID
    subject_id: UUID
    capabilities: list[str]
    qualifications: list[str]
    intervention_scope: str
    state: Literal['active','suspended','revoked']
    revision: int = Field(ge=1)
