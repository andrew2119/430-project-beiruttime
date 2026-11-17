"""Versioned responsibility for controlled unrepaired return."""
from datetime import timedelta
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, PositiveInt, Field


class RecoveryAssignment(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1]
    assignment_id: UUID
    assignment_revision: PositiveInt
    operator_id: UUID
    quote_id: UUID
    buyer_id: UUID
    organization_id: UUID
    operation_id: str = Field(min_length=1, max_length=128)


def recovery_record(assignment, now):
    return {
        **assignment.model_dump(mode='json'),
        'next_action': 'arrange_controlled_unrepaired_return',
        'held_since': now.isoformat(),
        'next_review_at': (now + timedelta(hours=24)).isoformat(),
        'escalate_at': (now + timedelta(hours=48)).isoformat(),
    }
