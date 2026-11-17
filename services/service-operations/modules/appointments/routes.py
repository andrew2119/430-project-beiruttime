"""Additive route factory; authenticated context and composition belong to the host."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from bt_contracts.service.appointments.v1 import Command
from .model import Rejected


def router_for(store, current_actor):
    router = APIRouter(prefix='/v1/appointments')

    def rejected(error):
        return JSONResponse(status_code=error.status, content={
            'error': {'code': error.code, 'details': {'candidates': list(error.candidates)}}},
            headers={'Cache-Control': 'no-store'})

    @router.post('/commands')
    async def command(request: Request, actor=Depends(current_actor)):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                return JSONResponse(status_code=413, content={'error': {'code': 'request_limit', 'details': {'candidates': []}}},
                                    headers={'Cache-Control': 'no-store'})
        try:
            body = Command.model_validate(json.loads(raw))
            result = await store.execute(body, actor.subject_id)
            return JSONResponse(content=result.model_dump(mode='json'), headers={'Cache-Control': 'no-store'})
        except (ValueError, ValidationError):
            return JSONResponse(status_code=422, content={'error': {'code': 'invalid_request', 'details': {'candidates': []}}},
                                headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return rejected(error)

    @router.get('/operations/{operation_id}')
    async def operation(operation_id: UUID, appointment_id: UUID, organization_id: UUID,
                        actor=Depends(current_actor)):
        try:
            result = await store.read(appointment_id, actor.subject_id, organization_id, operation_id)
            return JSONResponse(content=result.model_dump(mode='json'), headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return rejected(error)

    @router.get('/{appointment_id}')
    async def detail(appointment_id: UUID, organization_id: UUID, actor=Depends(current_actor)):
        try:
            result = await store.read(appointment_id, actor.subject_id, organization_id)
            return JSONResponse(content=result.model_dump(mode='json'), headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return rejected(error)

    return router
