"""Immutable close decision with a stable allocation recovery reference."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt
from .v2 import CloseResultV2


class CloseResultV3(CloseResultV2):
    schema_version: Literal[3] = 3
    assignment_required: bool = False
    operation_id: UUID
    revision: StrictInt = Field(ge=1)
    allocation_operation: str | None = Field(default=None, max_length=80)
    pending_reason: Literal["allocation_reconciliation", "legacy_reconciliation"] | None = None
    next_actor: Literal["auction", "operator"] | None = None
    next_review_at: AwareDatetime | None = None
    responsible_operator_id: UUID | None = None
    next_action: Literal["reconcile_allocation", "review_allocation_denial", "reconcile_legacy_purchase"] | None = None
    response_due_at: AwareDatetime | None = None
    escalation_due_at: AwareDatetime | None = None
    escalated_at: AwareDatetime | None = None
