"""Unregistered adapter: composition supplies current identity and durable storage."""
import asyncio
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.routing import APIRoute
from bt_contracts.service.finish.v1 import Command
from .service import Refusal


class BoundedRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            if request.method == 'POST':
                body = bytearray()
                try:
                    async with asyncio.timeout(2):
                        async for chunk in request.stream():
                            if len(body) + len(chunk) > 32768:
                                raise HTTPException(413)
                            body.extend(chunk)
                except TimeoutError:
                    raise HTTPException(503) from None
                request._body = bytes(body)
            return await handler(request)
        return bounded


def create_router(service_factory, principal):
    router = APIRouter(prefix='/v1/finish', tags=['finish consent'], route_class=BoundedRoute)

    def failure(error):
        status = {'denied': 403, 'not_found': 404, 'unavailable': 503}.get(error.code, 409)
        return HTTPException(status, detail={'code': error.code})

    @router.get('/subjects/{subject}')
    def detail(subject: UUID, actor: UUID = Depends(principal)):
        try:
            with service_factory() as service:
                return service.detail(actor, subject)
        except Refusal as error:
            raise failure(error) from None

    @router.post('/consents')
    def submit(body: Command, actor: UUID = Depends(principal)):
        try:
            with service_factory() as service:
                return service.submit(actor, body)
        except Refusal as error:
            raise failure(error) from None

    @router.get('/subjects/{subject}/operations/{operation}')
    def lookup(subject: UUID, operation: UUID, actor: UUID = Depends(principal)):
        try:
            with service_factory() as service:
                return service.lookup(actor, subject, operation)
        except Refusal as error:
            raise failure(error) from None

    return router
