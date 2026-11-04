"""Per-upstream bulkheads. No fixture transport is installed by production code."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
import jwt
from typing import Literal
from uuid import UUID
from pydantic import Field, ValidationError
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.models import Contract
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_events import OutboxRelay
from bt_runtime.principal import CurrentPrincipal, current_principal
from bt_contracts.catalog.options import Localized


class Brand(Contract):
    organization_id: UUID
    name: Localized
    kind: str
    status: str
    offerings: list[str] = Field(max_length=20)
    sample: bool = False


class DirectoryProfileV1(Contract):
    # Released Service Directory V1; public business names are not translated by this consumer.
    organization_id: UUID
    revision: int = Field(ge=1, strict=True)
    display_name: str = Field(min_length=2, max_length=120)
    kind: Literal['brand', 'dealer']
    sample: bool = Field(strict=True)
    capabilities: list[Literal['maintenance', 'cleaning', 'polishing', 'repair', 'bracelet_fit', 'customization']] = Field(max_length=6)
    contact: str = Field(max_length=160)
    visit_en: str = Field(max_length=400)
    visit_ar: str = Field(max_length=400)
    scope_en: str = Field(max_length=600)
    scope_ar: str = Field(max_length=600)


class DirectoryPageV1(Contract):
    items: list[DirectoryProfileV1] = Field(max_length=20)
    next_after: UUID | None


class OfficialBusinessV1(Contract):
    # Consumer projection of the released Identity businesses V1 contract, never local business authority.
    id: UUID
    public_name: str = Field(min_length=2, max_length=120)
    kind: Literal['brand', 'dealer']
    capabilities: list[Literal['sales', 'customization', 'servicing']] = Field(max_length=20)
    state: Literal['active', 'revoked']
    revision: int = Field(ge=1, strict=True)
    sample: bool = Field(strict=True)
    platform_onboarded: bool = Field(strict=True)
    authenticated_business: bool = Field(strict=True)
    independent_watch_authentication_required: Literal[False] = False


def clients(app):
    if not hasattr(app.state, "l10_clients"):
        app.state.l10_clients = {
            "identity": DependencyClient(
                "identity", os.getenv("IDENTITY_API_URL", "http://identity:8000"), timeout=1.5, concurrency=4
            ),
            "directory": DependencyClient(
                "service-operations",
                os.getenv("SERVICE_OPERATIONS_API_URL", "http://service-operations:8000"),
                timeout=1.5,
                concurrency=4,
            ),
            "communications": DependencyClient(
                "communications",
                os.getenv("COMMUNICATIONS_API_URL", "http://communications:8000"),
                timeout=1.5,
                concurrency=2,
            ),
        }
    return app.state.l10_clients


def unavailable():
    return PublicError("dependency_unavailable", "Brand options are temporarily unavailable. Try again.", status=503)


async def principal(request, organization_id: UUID | None = None):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192:
        raise PublicError("unauthorized", "Sign in to save your choices.", status=401)
    try:
        identity = clients(request.app)["identity"]
        if organization_id is None:
            result = await current_principal(identity, token, request.state.request_id)
        else:
            response = await identity.request(
                "GET",
                "/internal/v1/principal",
                params={"organization_id": str(organization_id)},
                headers={"Authorization": "Bearer " + token, "X-Request-ID": request.state.request_id},
            )
            if isinstance(response, Unavailable):
                raise unavailable()
            if response.status_code == 401:
                raise PublicError('unauthorized', 'Sign in to save your choices.', status=401)
            if response.status_code == 403:
                raise AccessDenied('Current organization scope could not be established')
            if response.status_code != 200:
                raise unavailable()
            result = CurrentPrincipal.model_validate(response.json())
    except (ValidationError, ValueError):
        raise unavailable() from None
    if isinstance(result, Unavailable):
        raise unavailable()
    return result


async def official_brand(request, organization_id):
    response = await clients(request.app)['identity'].request('GET', f'/v1/businesses/{organization_id}',
        headers={'X-Request-ID': request.state.request_id})
    if not isinstance(response, Unavailable) and response.status_code == 404:
        return None
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise unavailable()
    try:
        business = OfficialBusinessV1.model_validate(response.json())
        if business.id != organization_id:
            raise ValueError('Mismatched business')
    except (ValidationError, ValueError):
        raise unavailable() from None
    return business if business.kind == 'brand' and business.state == 'active' and business.platform_onboarded \
        and business.authenticated_business and 'customization' in business.capabilities else None


async def verified_brand(request, profile):
    if profile.kind != 'brand' or 'customization' not in profile.capabilities:
        return None
    business = await official_brand(request, profile.organization_id)
    if business is None:
        return None
    # A stale directory record cannot revive revoked onboarding or hide a sample marker.
    return Brand(organization_id=profile.organization_id,
        name=Localized(en=business.public_name, ar=business.public_name), kind='brand', status='onboarded',
        offerings=['customization'], sample=profile.sample or business.sample)


async def brands(request, after=None):
    params = {'purpose': 'customization', 'limit': 20}
    if after is not None:
        params['after'] = str(after)
    response = await clients(request.app)['directory'].request('GET', '/v1/directory/businesses', params=params,
        headers={'X-Request-ID': request.state.request_id})
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise unavailable()
    try:
        page = DirectoryPageV1.model_validate(response.json())
        ids = [item.organization_id for item in page.items]
        if ids != sorted(set(ids)) or (after is not None and any(item <= after for item in ids)) \
            or (page.next_after is not None and ((after is not None and page.next_after <= after)
                or any(item > page.next_after for item in ids))):
            raise ValueError('Non-progressing directory cursor')
    except (ValidationError, ValueError):
        raise unavailable() from None
    items = []
    try:
        async with asyncio.timeout(1.2):
            for start in range(0, len(page.items), 2):
                batch = await asyncio.gather(*(verified_brand(request, item) for item in page.items[start:start+2]))
                items.extend(item.model_dump(mode='json') for item in batch if item is not None)
    except TimeoutError:
        raise unavailable() from None
    # Preserve cursors even on fully filtered pages; never silently truncate the directory.
    return {'items': items, 'next_after': str(page.next_after) if page.next_after else None}


async def brand(request, brand_id):
    response = await clients(request.app)['directory'].request('GET', f'/v1/directory/businesses/{brand_id}',
        headers={'X-Request-ID': request.state.request_id})
    if not isinstance(response, Unavailable) and response.status_code in {404, 409}:
        found = None
    elif isinstance(response, Unavailable) or response.status_code != 200:
        raise unavailable()
    else:
        try:
            profile = DirectoryProfileV1.model_validate(response.json())
            if profile.organization_id != brand_id:
                raise ValueError('Mismatched directory entry')
        except (ValidationError, ValueError):
            raise unavailable() from None
        found = await verified_brand(request, profile)
    if found is None:
        raise PublicError('brand_unavailable', 'Choose an onboarded brand offering customization.', status=409)
    return found


class InboxDestination:
    """Communications Events V1: adapt only the convention path, keeping the same bulkhead."""
    def __init__(self, client):
        self.client = client
        self.timeout = client.timeout

    async def request(self, method, path, **kwargs):
        if method != 'POST' or path != '/internal/v1/events':
            raise ValueError('Only the registered outbox operation is supported')
        return await self.client.request(method, '/internal/v1/inbox/events', **kwargs)


def delivery_headers(app, destination):
    key = os.getenv('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    if key:
        now = datetime.now(timezone.utc)
        token = jwt.encode({'iss': app.state.settings.auth_issuer, 'sub': 'catalog', 'aud': destination,
            'type': 'service', 'iat': now, 'exp': now + timedelta(seconds=60)}, key.replace('\\n', '\n'), algorithm='RS256')
    else:
        token = os.getenv('BT_OPTIONS_EVENT_TOKEN', '')
    return {'Authorization': 'Bearer ' + token}


async def run(app, stop):
    dependencies = clients(app)
    try:
        relay = OutboxRelay(
            app.state.pool,
            {'communications': InboxDestination(dependencies['communications'])},
            headers=lambda destination: delivery_headers(app, destination),
        )
        while not stop.is_set():
            # Without a service credential, intent remains durable instead of unauthenticated publication.
            if os.getenv('BT_OPTIONS_EVENT_TOKEN') or os.getenv('BT_SERVICE_AUTH_PRIVATE_KEY'):
                await relay.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass
    finally:
        for dependency in dependencies.values():
            await dependency.aclose()
