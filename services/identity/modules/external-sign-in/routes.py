"""Opt-in route composition; no live provider or session implementation is selected."""
import asyncio
import importlib
import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .service import Denied, Stale

Callback = importlib.import_module('packages.contracts-identity.external-sign-in.current').Callback


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    operation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,100}$')


async def body(request, model):
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data) > 4096:
            raise Denied()
    return model.model_validate(json.loads(data))


def router_for(service, resolve_scope, *, origin: str):
    router = APIRouter()
    headers = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}

    async def dispatch(request, action):
        try:
            if (request.headers.get('origin') != origin and
                    not (request.method == 'GET' and 'origin' not in request.headers and
                         request.headers.get('sec-fetch-site') in (None, 'same-origin'))):
                raise Denied()
            scope = await asyncio.wait_for(resolve_scope(request), service.deadline)
            return JSONResponse(await action(scope), headers=headers)
        except Stale:
            return JSONResponse({'state': 'stale', 'en': 'Access changed. Sign in again.',
                                 'ar': 'تغيّر الوصول. سجّل الدخول مجددًا.'}, status_code=409, headers=headers)
        except (Denied, ValidationError, ValueError):
            return JSONResponse({'state': 'denied', 'en': 'Sign in or use account recovery.',
                                 'ar': 'سجّل الدخول أو استخدم استرداد الحساب.'}, status_code=403, headers=headers)
        except Exception:
            return JSONResponse({'state': 'unavailable', 'en': 'Try again with the same reference.',
                                 'ar': 'حاول مجددًا باستخدام المرجع نفسه.'}, status_code=503, headers=headers)

    @router.post('/v1/external-sign-in/challenges')
    async def start(request: Request):
        async def action(scope):
            command = await asyncio.wait_for(body(request, Start), service.deadline)
            return service.begin(command.operation_id, scope)
        return await dispatch(request, action)

    @router.post('/v1/external-sign-in/callback')
    async def callback(request: Request):
        async def action(scope):
            proof = request.headers.get('x-link-proof', '')
            if len(proof) > 256:
                raise Denied()
            return await service.callback(await asyncio.wait_for(body(request, Callback), service.deadline), scope, proof)
        return await dispatch(request, action)

    @router.get('/v1/external-sign-in/operations/{operation_id}')
    async def lookup(operation_id: str, request: Request):
        async def action(scope):
            if not 16 <= len(operation_id) <= 100:
                raise Denied()
            return await service.lookup(operation_id, scope)
        return await dispatch(request, action)

    return router
