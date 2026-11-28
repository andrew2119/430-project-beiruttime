"""Bounded private adapter; composition supplies the authoritative provider."""
import asyncio
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from pydantic import BaseModel, ConfigDict, Field

class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse({'error': {'code': 'invalid_proof'}}, status_code=422)
            except HTTPException as error:
                code = 'invalid_proof' if error.status_code < 500 else 'unavailable'
                response = JSONResponse({'error': {'code': code}}, status_code=error.status_code)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Pragma'] = 'no-cache'
            return response

        return private_handler


router = APIRouter(route_class=PrivateRoute)


class BrowserCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: int = Field(ge=1, le=1)
    operation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')
    expected_revision: int = Field(ge=0, strict=True)
    kind: str = Field(pattern=r'^(enroll|confirm|prove)$')
    proof: str | None = Field(default=None, max_length=64, repr=False)
    current_password: str | None = Field(default=None, max_length=128, repr=False)
    action: str | None = Field(default=None, pattern=r'^(seller_payout|business_payout|privileged_review|factor_change)$')
    record_id: str | None = Field(default=None, min_length=1, max_length=80)
    record_revision: int | None = Field(default=None, ge=0, strict=True)
    organization_id: str | None = Field(default=None, min_length=1, max_length=80)


class CurrentProvider(Protocol):
    async def status(self, request: Request) -> dict: ...
    async def command(self, request: Request, command: BrowserCommand) -> dict: ...


async def invoke(request, command=None):
    provider = getattr(request.app.state, 'two_factor_current_provider', None)
    headers = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}
    if provider is None:
        return JSONResponse({'error': {'code': 'unavailable'}}, status_code=503, headers=headers)
    try:
        # The provider owns current principal, exact origin, password proof and
        # source checks; request body never supplies an actor or a session.
        async with asyncio.timeout(2):
            result = await (provider.status(request) if command is None else provider.command(request, command))
        return JSONResponse(result, headers=headers)
    except Exception as error:
        code = getattr(error, 'code', 'unavailable')
        statuses = {'denied': 403, 'stale_revision': 409, 'conflict': 409,
                    'invalid_proof': 422, 'expired': 422, 'try_later': 429}
        if code not in statuses:
            code = 'unavailable'
        return JSONResponse({'error': {'code': code}}, status_code=statuses.get(code, 503), headers=headers)


@router.get('/v1/two-factor')
async def status(request: Request):
    return await invoke(request)


@router.post('/v1/two-factor')
async def command(body: BrowserCommand, request: Request):
    return await invoke(request, body)
