"""Private current-operation contract, version one."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal[1] = 1
    operation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')
    actor_id: str = Field(min_length=1, max_length=80)
    organization_id: str | None = Field(default=None, max_length=80)
    subject_id: str = Field(min_length=1, max_length=80)
    expected_revision: int = Field(ge=0, strict=True)
    kind: Literal['enroll', 'confirm', 'prove', 'consume', 'recover', 'revoke_ack']
    action: Literal['seller_payout', 'business_payout', 'privileged_review', 'factor_change'] | None = None
    record_id: str | None = Field(default=None, max_length=80)
    record_revision: int | None = Field(default=None, ge=0, strict=True)
    proof: str | None = Field(default=None, max_length=64, repr=False)
    proof_id: str | None = Field(default=None, max_length=80)


OPERATIONS = {
    'enroll': 'POST /internal/v1/two-factor/enrollment',
    'confirm': 'POST /internal/v1/two-factor/confirmation',
    'prove': 'POST /internal/v1/two-factor/proofs',
    'consume': 'POST /internal/v1/two-factor/consume',
    'recover': 'POST /internal/v1/two-factor/recovery',
    'revoke_ack': 'POST /internal/v1/two-factor/revocation-receipts',
    'lookup': 'GET /internal/v1/two-factor/operations/{operation_id}',
}
