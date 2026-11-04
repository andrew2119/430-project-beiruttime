"""CP S-08/S-09: fresh authority; CP B-18: durable identifiers-only intent."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import Literal
import jwt
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_events import OutboxRelay
from bt_runtime.principal import CurrentPrincipal


class OfficialBusiness(BaseModel):
    # Additive public Identity fields can evolve; only these fields convey authority.
    model_config = ConfigDict(extra='ignore')
    id: UUID
    public_name: str = Field(min_length=2, max_length=120)
    kind: Literal['brand', 'dealer']
    capabilities: list[Literal['sales', 'servicing', 'customization']] = Field(max_length=3)
    state: Literal['active', 'revoked']
    revision: int = Field(ge=1, strict=True)
    sample: bool = Field(strict=True)
    platform_onboarded: bool = Field(strict=True)
    authenticated_business: bool = Field(strict=True)
    independent_watch_authentication_required: Literal[False] = False


class InboxDestination:
    """Communications Events V1: adapt only the relay path, never its bounded transport."""
    def __init__(self, client):
        self.client = client
        self.timeout = client.timeout

    async def request(self, method, path, **kwargs):
        if method != 'POST' or path != '/internal/v1/events':
            raise ValueError('Only the registered outbox event operation is supported')
        return await self.client.request(method, '/internal/v1/inbox/events', **kwargs)


def identity_for(app):
    if not hasattr(app.state, 'l11_identity'):
        app.state.l11_identity = DependencyClient('identity', os.getenv('IDENTITY_API_URL', 'http://identity:8000'), timeout=0.5, concurrency=4)
    return app.state.l11_identity


async def principal(request: Request):
    return await scoped_principal(request)


async def scoped_principal(request: Request, organization_id: UUID | None = None):
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer ') or not 1 <= len(authorization[7:]) <= 8192:
        raise PublicError('unauthorized', 'Sign in to continue.', status=401)
    result = await identity_for(request.app).request('GET', '/internal/v1/principal',
        params={'organization_id': str(organization_id)} if organization_id else {},
        headers={'Authorization': authorization, 'X-Request-ID': request.state.request_id})
    if isinstance(result, Unavailable):
        raise PublicError('unavailable', 'Identity is temporarily unavailable.', status=503)
    # Preserve expired/revoked authentication so the browser can refresh or discard private state.
    if result.status_code == 401:
        raise PublicError('unauthorized', 'Sign in to continue.', status=401)
    if result.status_code == 403:
        raise AccessDenied('Current organization membership could not be established')
    if result.status_code != 200:
        raise PublicError('unavailable', 'Identity is temporarily unavailable.', status=503)
    try:
        return CurrentPrincipal.model_validate(result.json())
    except (ValidationError, ValueError):
        raise PublicError('unavailable', 'Identity is temporarily unavailable.', status=503) from None


async def official(request: Request, organization_id: UUID, *, brand_only=False, capability: str | None = None):
    response = await identity_for(request.app).request('GET', f'/v1/businesses/{organization_id}', headers={'X-Request-ID': request.state.request_id})
    if isinstance(response, Unavailable):
        raise PublicError('unavailable', 'Business verification is temporarily unavailable.', status=503)
    if response.status_code == 404:
        raise PublicError('not_official', 'An active onboarded business is required.', status=409)
    if response.status_code != 200:
        raise PublicError('unavailable', 'Business verification is temporarily unavailable.', status=503)
    try:
        business = OfficialBusiness.model_validate(response.json())
    except (ValidationError, ValueError):
        raise PublicError('unavailable', 'Business verification is temporarily unavailable.', status=503) from None
    if (business.id != organization_id or business.state != 'active'
            or not business.platform_onboarded or not business.authenticated_business
            or (brand_only and business.kind != 'brand')
            or (capability and capability not in business.capabilities)):
        raise PublicError('not_official', 'An active onboarded business is required.', status=409)
    return business


async def run(app, stop):
    identity = identity_for(app)
    communications = DependencyClient('communications', os.getenv('COMMUNICATIONS_API_URL', 'http://communications:8000'), timeout=1.2, concurrency=2)
    def headers(destination):
        key = os.getenv('BT_SERVICE_AUTH_PRIVATE_KEY', '')
        if not key:
            raise AccessDenied('Service signing is not configured')
        now = datetime.now(timezone.utc)
        token = jwt.encode({'iss': app.state.settings.auth_issuer, 'sub': app.state.settings.service_name, 'aud': destination, 'type': 'service', 'iat': now, 'exp': now + timedelta(seconds=60)}, key, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token}
    relay = OutboxRelay(app.state.pool, {'communications': InboxDestination(communications)}, headers=headers, batch_size=8, concurrency=2)
    try:
        # No configured signer means pending intent, not a competing relay that steals retries.
        if not os.getenv('BT_SERVICE_AUTH_PRIVATE_KEY', ''):
            await stop.wait()
            return
        while not stop.is_set():
            await relay.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass
    finally:
        await communications.aclose()
        await identity.aclose()
        if getattr(app.state, 'l11_identity', None) is identity:
            del app.state.l11_identity
