"""Additive route factory; the host supplies current authentication and storage."""
import asyncio
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError


def create_router(outbox, command_type, principal, producer):
    from .service import Rejected
    async def private_response(response: Response):
        response.headers['Cache-Control'] = 'no-store'
    router = APIRouter(dependencies=[Depends(private_response)])

    async def call(action):
        try:
            return await action
        except Rejected as error:
            return JSONResponse({'error': {'code': error.code}}, status_code=error.status,
                                headers={'Cache-Control': 'no-store'})

    @router.post('/internal/v1/transaction-email')
    async def capture(request: Request, identity=Depends(producer)):
        async def bounded_body():
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > 4096:
                    raise Rejected('invalid_request', 413)
                data.extend(chunk)
            return bytes(data)
        try:
            data = await asyncio.wait_for(bounded_body(), 2)
        except Rejected as error:
            return JSONResponse({'error': {'code': error.code}}, status_code=error.status, headers={'Cache-Control': 'no-store'})
        except TimeoutError:
            return JSONResponse({'error': {'code': 'unavailable'}}, status_code=503, headers={'Cache-Control': 'no-store'})
        try:
            command = command_type.model_validate_json(data)
        except ValidationError:
            return JSONResponse({'error': {'code': 'invalid_request'}}, status_code=422, headers={'Cache-Control': 'no-store'})
        return await call(outbox.capture(command, identity.actor_id, identity.organization_id))

    @router.get('/v1/transaction-email/operations/{operation_id}')
    async def lookup(operation_id: UUID, identity=Depends(principal)):
        return await call(outbox.lookup(operation_id, identity.actor_id, identity.organization_id, command_type))

    @router.get('/v1/transaction-email')
    async def listing(identity=Depends(principal), offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=50)):
        return await call(outbox.listing(identity.actor_id, identity.organization_id, command_type, offset, limit))

    @router.post('/v1/transaction-email/operations/{operation_id}/destination')
    async def destination(operation_id: UUID, identity=Depends(principal)):
        return await call(outbox.destination(operation_id, identity.actor_id, identity.organization_id, command_type))

    return router
