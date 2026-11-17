"""Private versioned adapter; absent transactional integration fails closed."""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_contracts.orders.cancellations.v1 import Command, Result
from service_app.orders_dependencies import principal
from .service import execute, lookup, Denied, Conflict, Unavailable

router = APIRouter(tags=['cancellations-v1'])


async def respond(call):
    try:
        return await call
    except Denied:
        raise HTTPException(403, 'scope_denied') from None
    except Conflict:
        raise HTTPException(409, 'operation_conflict') from None
    except Unavailable:
        raise HTTPException(503, 'resolve_same_operation') from None


@router.post('/v1/cancellations', response_model=Result)
async def submit(body: Command, request: Request, actor=Depends(principal)):
    return await respond(execute(getattr(request.app.state, 'cancellations_provider', None),
                                 body, actor, datetime.now(timezone.utc)))


@router.get('/v1/cancellations/operations/{operation_id}', response_model=Result)
async def operation(operation_id: UUID, subject_id: UUID, request: Request, actor=Depends(principal)):
    return await respond(lookup(getattr(request.app.state, 'cancellations_provider', None),
                                subject_id, operation_id, actor))
