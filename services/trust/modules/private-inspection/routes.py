"""Route factory. The host supplies current authenticated scope and persistence."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


COPY = {
    'en': 'The inspection could not be confirmed. Refresh the current record or retry the same action reference.',
    'ar': 'تعذّر تأكيد الفحص. حدّث السجل الحالي أو أعد المحاولة باستخدام مرجع الإجراء نفسه.',
}


class InspectionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={
                    'error': {'code': 'invalid_request', 'message': COPY, 'request_id': ''}},
                    headers={'Cache-Control': 'no-store'})

        return validated


def router_for(service, current_scope):
    router = APIRouter(prefix='/v1/private-inspections', tags=['private-inspections'],
                       route_class=InspectionRoute)

    async def invoke(call):
        try:
            return JSONResponse(content=await call, headers={'Cache-Control': 'no-store'})
        except Exception as error:
            if not hasattr(error, 'code') or not hasattr(error, 'status'):
                raise
            return JSONResponse(status_code=error.status, content={
                'error': {'code': error.code, 'message': COPY, 'request_id': ''}},
                headers={'Cache-Control': 'no-store'})

    @router.post('/results')
    async def submit(request: Request, scope=Depends(current_scope)):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 16384:
                return JSONResponse(status_code=413, content={'error': {'code': 'request_limit', 'message': COPY}})
        try:
            body = json.loads(data)
            if not isinstance(body, dict):
                raise ValueError('object_required')
        except (ValueError, UnicodeError):
            return JSONResponse(status_code=422, content={'error': {'code': 'invalid_request', 'message': COPY}})
        return await invoke(service.submit(scope.actor_id, scope.organization_id, body))

    @router.get('/operations/{operation_id}')
    async def lookup(operation_id: UUID, subject_id: UUID, scope=Depends(current_scope)):
        return await invoke(service.lookup(scope.actor_id, scope.organization_id, subject_id, operation_id))

    @router.get('/{subject_id}/workspace')
    async def workspace(subject_id: UUID, scope=Depends(current_scope)):
        return await invoke(service.workspace(scope.actor_id, scope.organization_id, subject_id))

    @router.get('/{subject_id}/current')
    async def current(subject_id: UUID, scope=Depends(current_scope)):
        return await invoke(service.current(scope.actor_id, scope.organization_id, subject_id))

    @router.get('/{subject_id}/return-readiness')
    async def readiness(subject_id: UUID, scope=Depends(current_scope)):
        return await invoke(service.return_readiness(scope.actor_id, scope.organization_id, subject_id))

    return router
