"""Additive adapter; runtime composition supplies current scoped identity and store."""
import asyncio
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from .store import Rejected


class BoundedRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def bounded(request: Request):
            if request.method == 'POST':
                chunks = bytearray()
                try:
                    async with asyncio.timeout(2):
                        async for chunk in request.stream():
                            if len(chunks) + len(chunk) > 131072:
                                raise HTTPException(413)
                            chunks.extend(chunk)
                except TimeoutError:
                    raise HTTPException(408) from None
                request._body = bytes(chunks)
            return await handler(request)
        return bounded


def create_router(store, current_scope, clock=lambda: datetime.now(timezone.utc)):
    router = APIRouter(prefix='/internal/v1/authorized-work', route_class=BoundedRoute)
    command_type = store.contract.Command

    async def execute(body, scope):
        try:
            return await store.execute(body, scope.actor_id, scope.organization_id, clock())
        except Rejected as error:
            code = str(error)
            return JSONResponse(status_code=503 if code == 'unavailable' else 403 if code == 'denied' else 409,
                content={'error':{'code':code,'message':code,'request_id':'','details':{'not_applied':error.not_applied}}})

    async def post(body: command_type, scope=Depends(current_scope)):
        return await execute(body, scope)

    async def get(operation_id: UUID, scope=Depends(current_scope)):
        try:
            return await store.lookup(operation_id, scope.actor_id, scope.organization_id, clock())
        except Rejected as error:
            code = str(error)
            raise HTTPException(503 if code == 'unavailable' else 403, detail={'code': code}) from None

    async def context(subject_id: UUID, scope=Depends(current_scope)):
        try:
            return await store.context(subject_id, scope.actor_id, scope.organization_id, clock())
        except Rejected as error:
            raise HTTPException(503 if str(error) == 'unavailable' else 403,
                                detail={'code': str(error)}) from None

    async def history(subject_id: UUID, offset: int = 0, scope=Depends(current_scope)):
        try:
            return await store.history(subject_id, scope.actor_id, scope.organization_id, clock(), offset)
        except Rejected as error:
            raise HTTPException(503 if str(error) == 'unavailable' else 403,
                                detail={'code': str(error)}) from None

    router.add_api_route('/subjects/{subject_id}/observations', history, methods=['GET'])
    router.add_api_route('/subjects/{subject_id}', context, methods=['GET'])
    router.add_api_route('/commands', post, methods=['POST'])
    router.add_api_route('/operations/{operation_id}', get, methods=['GET'])
    return router
