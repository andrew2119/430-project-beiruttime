"""Authenticated targeted delivery with atomic per-recipient receipts."""
import asyncio
from uuid import UUID
import jwt
from fastapi import APIRouter, HTTPException, Request
from bt_runtime.app.db import unit_of_work
from bt_contracts_core.models import EventEnvelope
from bt_contracts.comms.saved_searches.models import Publication
from . import service
from .http import BoundedRoute

router = APIRouter(route_class=BoundedRoute)


@router.post('/internal/v1/saved-searches/events')
async def events(event: EventEnvelope, request: Request):
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise HTTPException(503)
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    try:
        claims = jwt.decode(token, settings.service_auth_public_key, algorithms=['RS256'],
                            issuer=settings.auth_issuer, audience=settings.service_name,
                            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'type']})
        if claims['type'] != 'service' or claims['sub'] != 'catalog':
            raise HTTPException(403)
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    if event.source != 'catalog' or event.type != 'catalog.listing-published.v1':
        raise HTTPException(403)
    try:
        data = dict(event.data)
        owner = UUID(data.pop('recipient_id'))
        publication = Publication.model_validate(data)
    except (ValueError, TypeError, KeyError):
        service.fail('invalid_publication', 422)
    if event.subject != str(publication.listing_id) or event.time != publication.published_at:
        service.fail('invalid_publication', 422)
    # The occurrence is a source publication, while envelope IDs may differ per recipient.
    try:
        async with asyncio.timeout(8):
            async with unit_of_work(request.app.state.pool, lock_key='saved-searches:' + str(owner)) as tx:
                await tx.execute("SET LOCAL idle_in_transaction_session_timeout='8000'")
                await service.deliver(tx, owner, publication, getattr(request.app.state, 'saved_search_catalog', None))
    except TimeoutError:
        service.fail('unavailable', 503)
    return {'accepted': True}
