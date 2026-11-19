"""Additive route factory; the host owns mounting and device capability cookies."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from .service import Conflict, Denied, Pending


def build_router(service, command_type, credential, device_capability, application_server_key=None):
    router = APIRouter(prefix='/v1/browser-push')

    async def invoke(call):
        try:
            return await call
        except Denied:
            raise HTTPException(403, detail={'code': 'denied'}) from None
        except Conflict:
            raise HTTPException(409, detail={'code': 'stale_revision'}) from None
        except Pending:
            raise HTTPException(503, detail={'code': 'unavailable'}) from None

    @router.get('/config')
    async def config(request: Request):
        await invoke(service.identity(await credential(request)))
        if not application_server_key:
            raise HTTPException(503, detail={'code': 'unavailable'})
        return {'application_server_key': application_server_key}

    @router.post('/devices')
    async def command(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 4096:
                raise HTTPException(413, detail={'code': 'request_too_large'})
        try:
            body = command_type.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, detail={'code': 'invalid_request'}) from None
        return await invoke(service.command(await credential(request), await device_capability(request), body))

    @router.get('/devices/{device_id}')
    async def device(device_id: UUID, request: Request):
        return await invoke(service.device(await credential(request), await device_capability(request), device_id))

    @router.get('/operations/{operation_id}')
    async def lookup(operation_id: UUID, request: Request):
        return await invoke(service.lookup(await credential(request), operation_id))

    @router.get('/notices/{notice_id}/destination')
    async def destination(notice_id: UUID, request: Request):
        return await invoke(service.destination(await credential(request), notice_id))

    return router
