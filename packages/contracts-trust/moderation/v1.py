"""Versioned moderation command/event schemas; private evidence is not an event field."""
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator
from bt_contracts_core.models import Contract


class Report(Contract):
    target_kind: Literal['listing','user','message']
    target_id: UUID
    category: Literal['counterfeit','misleading','harassment','payment_abuse','other']
    evidence: str = Field(min_length=1,max_length=4000)

    @field_validator('evidence')
    @classmethod
    def meaningful_evidence(cls,value):
        if not value.strip():
            raise ValueError('Evidence is required')
        return value.strip()


class Decision(Contract):
    action: Literal['warn','hide','suspend','reinstate','dismiss']
    reason: str = Field(min_length=3,max_length=4000)

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls,value):
        if len(value.strip())<3:
            raise ValueError('Reason is required')
        return value.strip()


class Appeal(Contract):
    reason: str = Field(min_length=3,max_length=4000)

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls,value):
        if len(value.strip())<3:
            raise ValueError('Reason is required')
        return value.strip()


class AssignmentRelease(Appeal):
    """A reasoned assignment change, not a private-case access grant."""


class DecisionEvent(Contract):
    case_id: UUID
    target_kind: Literal['listing','user','message']
    target_id: UUID
    action: Literal['warn','hide','suspend','reinstate','dismiss']
    revision: int = Field(ge=1)
    preserve_transaction_duties: Literal[True] = True
