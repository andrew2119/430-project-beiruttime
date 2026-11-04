"""A narrow authenticated inbox, separate from the bid-notices receiver."""

from typing import Literal
from uuid import UUID
import jwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StrictInt, StrictBool, ValidationError
from bt_contracts_core.models import Contract, EventEnvelope
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from bt_events import consume

router = APIRouter()
ALLOWED = {"catalog.listing.draft-saved.v1", "catalog.listing.media-updated.v1", "catalog.listing.published.v1"}


class ListingUpdate(Contract):
    listing_id: UUID
    revision: StrictInt = Field(ge=1)
    seller_id: UUID
    organization_id: UUID | None
    status: Literal["draft", "publication_pending", "published"]
    is_demo: StrictBool


async def project(tx, event):
    try:
        update = ListingUpdate.model_validate(event.data)
    except ValidationError:
        raise PublicError("invalid_event", "Invalid listing update.", status=422) from None
    if event.subject != str(update.listing_id):
        raise PublicError("invalid_event_binding", "Event resource binding differs.", status=422)
    await tx.execute(
        """INSERT INTO seller_workspace_updates(listing_id,seller_id,organization_id,revision,event_type,occurred_at)
        VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(listing_id) DO UPDATE SET revision=excluded.revision,
        event_type=excluded.event_type,occurred_at=excluded.occurred_at,received_at=now()
        WHERE seller_workspace_updates.revision<excluded.revision""",
        update.listing_id,
        update.seller_id,
        update.organization_id,
        update.revision,
        event.type,
        event.time,
    )


@router.post("/internal/v1/seller-workspace/events")
async def receive(event: EventEnvelope, request: Request):
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise HTTPException(503)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or len(token) > 8192:
        raise HTTPException(401)
    try:
        claims = jwt.decode(
            token,
            settings.service_auth_public_key,
            algorithms=["RS256"],
            issuer=settings.auth_issuer,
            audience="communications",
            options={"require": ["exp", "iat", "iss", "aud", "sub", "type"]},
        )
        if (
            claims["sub"] != "catalog"
            or claims["type"] != "service"
            or event.source != "catalog"
            or event.type not in ALLOWED
        ):
            raise HTTPException(403)
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    async with unit_of_work(request.app.state.pool) as tx:
        accepted = await consume(tx, "seller-workspace.v1", event, project)
    return {"accepted": accepted}
