"""Trust decisions change visibility, never physical allocations or buyer duties."""

from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt, ValidationError
from bt_contracts_core.models import Contract
from bt_contracts_core.errors import PublicError
from bt_runtime.event_http import build_event_router
from bt_runtime.demo_seed import HANDOFF_TYPE
from .handoff import receive as receive_handoff


class ModerationDecision(Contract):
    case_id: UUID
    target_kind: Literal["listing", "user", "message"]
    target_id: UUID
    action: Literal["warn", "hide", "suspend", "reinstate", "dismiss"]
    revision: StrictInt = Field(ge=1)
    preserve_transaction_duties: Literal[True]


async def apply(tx, event):
    try:
        decision = ModerationDecision.model_validate(event.data)
    except ValidationError:
        raise PublicError("invalid_event", "Invalid moderation decision.", status=422) from None
    if decision.target_kind != "listing":
        raise PublicError("invalid_event_target", "This decision is not for Catalog.", status=422)
    row = await tx.fetchrow("SELECT id FROM catalog_listings WHERE id=$1 FOR UPDATE", decision.target_id)
    if row is None:
        raise PublicError("not_found", "Listing not found.", status=404)
    previous = await tx.fetchrow("SELECT * FROM catalog_moderation_cases WHERE case_id=$1", decision.case_id)
    if previous and previous["listing_id"] != decision.target_id:
        raise PublicError("invalid_event_binding", "Moderation case target differs.", status=422)
    if previous and previous["revision"] >= decision.revision:
        return
    hidden = (
        decision.action == "hide" if decision.action in ("hide", "reinstate") else bool(previous and previous["hidden"])
    )
    saved = await tx.fetchval(
        """INSERT INTO catalog_moderation_cases(case_id,listing_id,revision,hidden) VALUES($1,$2,$3,$4)
        ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,hidden=excluded.hidden,updated_at=now()
        WHERE catalog_moderation_cases.listing_id=excluded.listing_id AND catalog_moderation_cases.revision<excluded.revision
        RETURNING listing_id""",
        decision.case_id,
        decision.target_id,
        decision.revision,
        hidden,
    )
    if saved is None:
        raise PublicError("invalid_event_binding", "Moderation case target differs.", status=422)
    # A case's reinstatement clears that case's hold, not another unresolved hold.
    # Fact/fee revisions stay bound to the physical fence; visibility is orthogonal.
    await tx.execute(
        """UPDATE catalog_listings SET is_hidden=EXISTS(
        SELECT 1 FROM catalog_moderation_cases WHERE listing_id=$1 AND hidden),updated_at=now() WHERE id=$1""",
        decision.target_id,
    )


# Catalog's one event route: Identity's demo seed handoff is registered here too, under the same consumer.
router = build_event_router(
    "catalog.moderation.v1",
    {"trust.moderation.decided.v1": ("trust", apply), HANDOFF_TYPE: ("identity", receive_handoff)},
)
