"""Source-owned current watch and responsible assignment commands."""

from uuid import UUID
from pydantic import Field, StrictInt
from .v2 import Wire


class WatchBinding(Wire):
    operation_id: UUID
    source_revision: StrictInt = Field(ge=1, le=2147483647)
    expected_binding_revision: StrictInt = Field(ge=0, le=2147483647)
    request_revision: StrictInt = Field(ge=1, le=2147483647)
    buyer_id: UUID
    brand_id: UUID
    watch_id: UUID


class AssignmentBinding(WatchBinding):
    assessor_id: UUID
    approver_id: UUID
    quality_reviewer_id: UUID
    recovery_operator_id: UUID


class CurrentBinding(Wire):
    request_id: UUID
    request_revision: StrictInt = Field(ge=1, le=2147483647)
    binding_revision: StrictInt = Field(ge=0, le=2147483647)
    watch_id: UUID | None
    assessor_id: UUID | None
    approver_id: UUID | None
    quality_reviewer_id: UUID | None
    recovery_operator_id: UUID | None
