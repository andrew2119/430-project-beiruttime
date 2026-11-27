"""Fail-closed current assigned-record scope for every private read and write."""
from .current_provider import CurrentAuthority
import asyncio
from fastapi import HTTPException, Request
from bt_contracts.service.intake.current import RecordAccess, RecordListAccess

async def record_access(p, request, org, order_id, permission):
    provider = getattr(request.app.state, 'intake_current_authority', None)
    if provider is None and isinstance(request, Request):
        provider = CurrentAuthority(request)
    if provider is None:
        raise HTTPException(503)
    try:
        value = RecordAccess.model_validate(await asyncio.wait_for(
            provider.record_access(p.actor.subject_id, org, order_id, permission), timeout=1.2))
    except (TimeoutError, ConnectionError, ValueError):
        raise HTTPException(503) from None
    if (value.actor_id, value.organization_id, value.order_id, value.permission, value.allowed) != (
            p.actor.subject_id, org, order_id, permission, True):
        raise HTTPException(403)
    return value

async def readable_orders(p, request, org):
    provider = getattr(request.app.state, 'intake_current_authority', None)
    if provider is None and isinstance(request, Request):
        provider = CurrentAuthority(request)
    if provider is None:
        raise HTTPException(503)
    try:
        value = RecordListAccess.model_validate(await asyncio.wait_for(
            provider.readable_orders(p.actor.subject_id, org), timeout=1.2))
    except (TimeoutError, ConnectionError, ValueError):
        raise HTTPException(503) from None
    if (value.actor_id, value.organization_id) != (p.actor.subject_id, org):
        raise HTTPException(403)
    return value.order_ids
