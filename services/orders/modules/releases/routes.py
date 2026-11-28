"""Additive route factory; composition and current authentication belong to Orders."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from .contracts import Command, Context
from .service import Denied, Releases


def router_for(releases: Releases, current_context):
    router = APIRouter(tags=["releases-v1"])

    async def call(awaitable):
        try:
            return await awaitable
        except Denied:
            raise HTTPException(403, detail="release_denied") from None
        except (TimeoutError, ConnectionError):
            raise HTTPException(503, detail="release_unavailable") from None

    @router.get("/v1/releases/operations/{operation_id}")
    async def operation(operation_id: UUID, context: Context = Depends(current_context)):
        return await call(releases.lookup(context, operation_id))

    @router.post("/v1/releases/operations/{operation_id}/recover")
    async def recover(operation_id: UUID, context: Context = Depends(current_context)):
        return await call(releases.recover(context, operation_id))

    @router.get("/v1/releases/{order_id}")
    async def current(order_id: UUID, context: Context = Depends(current_context)):
        return await call(releases.current(context, order_id))

    @router.post("/v1/releases")
    async def release(request: Request, context: Context = Depends(current_context)):
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > 8192:
                raise HTTPException(413, detail="release_request_too_large")
            chunks.append(chunk)
        try:
            command = Command.model_validate_json(b"".join(chunks))
        except ValidationError:
            raise HTTPException(422, detail="release_request_invalid") from None
        if command.actor_id != context.actor_id or command.organization_id != context.organization_id:
            raise HTTPException(403, detail="release_denied")
        return await call(releases.submit(command))

    return router
