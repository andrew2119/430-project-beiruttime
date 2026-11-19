"""Additive route factory. The Orders composition root owns mounting."""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .adapter import Adapter


def build_router(custody, authenticated_context):
    router = APIRouter()
    adapter = Adapter(custody)

    async def decode(request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                return None
        try:
            value = json.loads(body)
            return value if isinstance(value, dict) else None
        except (ValueError, UnicodeError):
            return None

    @router.get("/v1/custody/{order_id}")
    def read(order_id: str, context=Depends(authenticated_context)):
        status, body = adapter.call("read", context, order_id=order_id)
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    @router.get("/v1/custody/{order_id}/history")
    def history(order_id: str, offset: int = 0, limit: int = 25, context=Depends(authenticated_context)):
        status, body = adapter.call("history", context, order_id=order_id, offset=offset, limit=limit)
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    @router.get("/internal/v1/custody/{order_id}/operations/{operation_id}")
    def lookup(order_id: str, operation_id: str, context=Depends(authenticated_context)):
        status, body = adapter.call("lookup", context, order_id=order_id, operation_id=operation_id)
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    @router.post("/internal/v1/custody/commands")
    @router.post("/v1/custody/{order_id}/buyer-receipts")
    async def command(request: Request, order_id: str | None = None, context=Depends(authenticated_context)):
        body = await decode(request)
        if body is None or (order_id is not None and (
            body.get("action") != "buyer_receipt" or body.get("subject_id") != order_id
        )):
            return JSONResponse({"schema_version": "custody.v1", "state": "invalid"}, status_code=422)
        from starlette.concurrency import run_in_threadpool
        status, result = await run_in_threadpool(adapter.call, "command", context, command=body)
        return JSONResponse(result, status_code=status, headers={"Cache-Control": "no-store"})

    return router
