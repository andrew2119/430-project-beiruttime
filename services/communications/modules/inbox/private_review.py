"""Scoped identity review delivery."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from bt_contracts.comms.inbox.models import NoticeInput
from bt_contracts.comms.inbox.private_review import PrivateReviewV1
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import consume
from bt_runtime.app.db import unit_of_work
from .events import authorize, persist_notice

router = APIRouter()
TYPES = {
    "identity.private-review-assigned.v1": "case_update",
    "identity.private-seller-reviewed.v1": "case_update",
}


async def store(tx, event):
    try:
        data = PrivateReviewV1.model_validate(event.data)
    except ValidationError:
        raise PublicError(
            "invalid_notice", "Review fields are invalid.", status=422
        ) from None
    if event.subject != str(data.subject_id) or data.subject_id == data.reviewer_id:
        raise PublicError(
            "invalid_notice", "Review recipient fields differ.", status=422
        )
    for recipient in (data.subject_id, data.reviewer_id):
        await persist_notice(
            tx,
            "identity",
            NoticeInput(
                occurrence_id=str(event.id),
                recipient_id=recipient,
                kind=TYPES[event.type],
                resource_id=data.review_id,
                resource_owner_id=recipient,
                resource_revision=data.revision,
                event_time=event.time,
            ),
        )


@router.post("/internal/v1/inbox/private-review/events")
async def receive(event: EventEnvelope, request: Request):
    authorize(request, event.source)
    if event.source != "identity" or event.type not in TYPES:
        raise HTTPException(403)
    async with unit_of_work(request.app.state.pool) as tx:
        accepted = await consume(tx, "L07.private-review", event, store)
    return {"accepted": accepted}
