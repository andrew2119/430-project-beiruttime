"""Authenticated, opt-in event ingestion; never expose a general public bus."""
from typing import Awaitable, Callable
import jwt
from fastapi import APIRouter, HTTPException, Request
from bt_contracts_core.models import EventEnvelope
from bt_events import consume
from .app.db import unit_of_work


def build_event_router(consumer: str, handlers: dict[str, tuple[str, Callable[..., Awaitable[None]]]]) -> APIRouter:
    router = APIRouter()

    @router.post('/internal/v1/events')
    async def receive(event: EventEnvelope, request: Request):
        settings = request.app.state.settings
        if not settings.service_auth_public_key:
            raise HTTPException(503)
        scheme, _, token = request.headers.get('Authorization', '').partition(' ')
        if scheme.lower() != 'bearer' or len(token) > 8192:
            raise HTTPException(401)
        try:
            claims = jwt.decode(token, settings.service_auth_public_key, algorithms=['RS256'],
                issuer=settings.auth_issuer, audience=settings.service_name,
                options={'require': ['exp','iat','iss','aud','sub','type']})
            if claims['type'] != 'service' or claims['sub'] != event.source:
                raise HTTPException(403)
        except jwt.InvalidTokenError:
            raise HTTPException(401) from None
        registration = handlers.get(event.type)
        if registration is None or registration[0] != event.source:
            raise HTTPException(403)
        async with unit_of_work(request.app.state.pool) as tx:
            accepted = await consume(tx, consumer, event, registration[1])
        return {'accepted': accepted}

    return router
