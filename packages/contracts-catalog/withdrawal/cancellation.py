"""Versioned no-bid cancellation boundary; serialization belongs to Auction."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictInt, model_validator
from bt_contracts_core.models import Contract


class Cancellation(Contract):
    schema_version: Literal["listing-cancellation.v1"] = "listing-cancellation.v1"
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=200)


class CancellationResult(Cancellation):
    state: Literal["pending", "denied", "succeeded"]
    revision: StrictInt = Field(ge=1)
    pending_reason: Literal["reconciliation_required"] | None = None
    next_actor: Literal["seller", "operator"]
    next_review_at: AwareDatetime | None = None
    code: Literal[
        "withdrawn",
        "bid_exists",
        "sale_commitment",
        "stale_revision",
        "reconciliation_required",
    ]
    explanation: dict[Literal["en", "ar"], str]
    next_action: Literal["none", "exception_route", "reload", "retry_same_operation"]

    @model_validator(mode="after")
    def coherent_result(self):
        if set(self.explanation) != {"en", "ar"} or any(
            not text.strip() or len(text) > 500 for text in self.explanation.values()
        ):
            raise ValueError("Complete bounded explanations are required.")
        if self.revision < self.expected_revision:
            raise ValueError("Result revision cannot precede the source revision.")
        if self.state == "succeeded":
            if (
                self.revision != self.expected_revision + 1
                or self.code != "withdrawn"
                or self.next_action != "none"
                or self.next_actor != "seller"
                or self.pending_reason is not None
                or self.next_review_at is not None
            ):
                raise ValueError("Success must bind the single guarded transition.")
        elif self.state == "pending":
            if (
                self.code != "reconciliation_required"
                or self.pending_reason != self.code
                or self.next_actor != "operator"
                or self.next_review_at is None
                or self.next_action != "retry_same_operation"
            ):
                raise ValueError(
                    "Pending requires an assigned recovery action and review time."
                )
        elif (
            self.code not in {"bid_exists", "sale_commitment", "stale_revision"}
            or self.next_actor != "seller"
            or self.pending_reason is not None
            or self.next_review_at is not None
            or self.next_action
            != ("reload" if self.code == "stale_revision" else "exception_route")
        ):
            raise ValueError("Denial requires a reason and a matching recovery action.")
        return self


def matches_result(value, command):
    """Unbound or malformed replies never settle a retained operation."""
    try:
        result = CancellationResult.model_validate(value)
        original = Cancellation.model_validate(command)
    except (ValueError, TypeError):
        return False
    return all(
        getattr(result, field) == getattr(original, field)
        for field in Cancellation.model_fields
    )
