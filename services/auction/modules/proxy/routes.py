from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, StrictInt
from bt_contracts_core.models import Contract
from bt_runtime.app.auth import require_principal
from .proxy import MAX_MINOR

router = APIRouter(prefix='/v1/auctions', tags=['private-maximum'])


class MaximumCommand(Contract):
    """Same wire fields as Auction core BidCommand v1; no client actor or time."""
    amount_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    fee_quote_id: UUID
    expected_revision: StrictInt = Field(ge=1)


@router.post('/{auction_id}/maximum', dependencies=[Depends(require_principal)])
async def maximum(request: Request, auction_id: UUID, command: MaximumCommand):
    admission = getattr(request.app.state, 'auction', None)
    if admission is None:
        raise HTTPException(503)
    # Frozen L05 seam: all permissions, sequencing, idempotency, private state,
    # sanitized history and outbox writes share the one authoritative transaction.
    return await admission.submit(request, auction_id, command, kind='maximum')
