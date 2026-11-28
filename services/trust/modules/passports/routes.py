"""Additive routes; composition supplies authenticated current identity."""
import asyncio
from collections.abc import Callable
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from .core import Failure, Issue, Passports, Signed


def router_for(service: Passports, current_actor: Callable) -> APIRouter:
    router = APIRouter()

    def result(call):
        try:
            return call().model_dump(mode='json')
        except Failure as error:
            raise HTTPException(error.status, detail={'code': error.code}) from None

    async def body(request, model):
        data = bytearray()
        try:
            async with asyncio.timeout(2.0):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 4096:
                        raise HTTPException(413, detail={'code': 'request_limit'})
                    data.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, detail={'code': 'request_timeout'}) from None
        try:
            return model.model_validate_json(bytes(data))
        except ValidationError:
            raise HTTPException(422, detail={'code': 'invalid_request'}) from None

    @router.post('/internal/v1/passports')
    async def issue(request: Request, actor: UUID = Depends(current_actor)):
        command = await body(request, Issue)
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(result, lambda: service.issue(actor, command))

    @router.get('/internal/v1/passports/operations/{operation_id}')
    def lookup(operation_id: UUID, actor: UUID = Depends(current_actor)):
        return result(lambda: service.lookup(actor, operation_id))

    @router.get('/public/v1/passports/{passport_id}')
    def public(passport_id: UUID, request: Request):
        if request.query_params:
            raise HTTPException(403, detail={'code': 'private_fields_denied'})
        return result(lambda: service.public(passport_id))

    @router.post('/public/v1/passports/verify')
    async def verify(request: Request):
        document = await body(request, Signed)
        return result(lambda: service.verify(document))

    return router
