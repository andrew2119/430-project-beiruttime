"""Additive route; composition supplies a current public provider."""
from typing import Annotated
from fastapi import APIRouter, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from .contracts import CompareRequest, Comparison
from .service import compare


def invalid_request(status=422):
    return JSONResponse(status_code=status, headers={'Cache-Control': 'no-store'}, content={
        'error': {'code': 'invalid_comparison', 'message': {
            'en': 'Choose up to three distinct public listing references.',
            'ar': 'اختر حتى ثلاثة مراجع إعلانات عامة غير مكررة.',
        }},
    })


class BoundedReadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    return invalid_request(413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
            try:
                return await handler(request)
            except (RequestValidationError, HTTPException):
                # Validation must not echo arbitrary submitted private content.
                return invalid_request()
        return bounded


router = APIRouter(prefix='/v1/comparison', tags=['comparison'], route_class=BoundedReadRoute)


@router.post('/operations/{operation_id}', response_model=Comparison)
async def current_operation(operation_id: Annotated[str, Path(pattern=r'^[A-Za-z0-9_-]{1,100}$')],
                            body: CompareRequest, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return await compare(operation_id, body, getattr(request.app.state, 'comparison_public_provider', None))
