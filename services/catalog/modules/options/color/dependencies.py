"""Per-upstream bulkheads. No fixture transport is installed by production code."""

import asyncio
import os
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


class BrandPage(Contract):
    items: list[Brand] = Field(max_length=100)


class OfficialBusinessV1(Contract):
    # Consumer projection of the released Identity businesses V1 contract, never local business authority.
    id: UUID
    public_name: str = Field(min_length=2, max_length=120)
    kind: Literal['brand', 'dealer']
    capabilities: list[Literal['sales', 'customization', 'servicing']] = Field(max_length=20)
    state: Literal['active', 'revoked']
    revision: int = Field(ge=1)
    sample: bool
    platform_onboarded: bool
    authenticated_business: bool
    independent_watch_authentication_required: Literal[False] = False


class BusinessPage(Contract):
    items: list[OfficialBusinessV1] = Field(max_length=100)


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
            if response.status_code != 200:
                raise AccessDenied("Current organization scope could not be established")
            result = CurrentPrincipal.model_validate(response.json())
    except (ValidationError, ValueError):
        raise unavailable() from None
    if isinstance(result, Unavailable):
        raise unavailable()
    return result


async def directory_brands(request):
    response = await clients(request.app)["directory"].request(
        "GET",
        "/v1/directory",
        params={"kind": "brand", "offering": "customization"},
        headers={"X-Request-ID": request.state.request_id},
    )
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise unavailable()
    try:
        page = BrandPage.model_validate(response.json())
    except (ValidationError, ValueError):
        raise unavailable() from None
    return [b for b in page.items if b.kind == "brand" and b.status == "onboarded" and "customization" in b.offerings]


async def official_brands(request):
    response = await clients(request.app)['identity'].request('GET', '/v1/businesses',
        headers={'X-Request-ID': request.state.request_id})
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise unavailable()
    try:
        page = BusinessPage.model_validate(response.json())
    except (ValidationError, ValueError):
        raise unavailable() from None
    return {b.id: b for b in page.items if b.kind == 'brand' and b.state == 'active'
            and b.platform_onboarded and b.authenticated_business and 'customization' in b.capabilities}


async def brands(request):
    directory, official = await asyncio.gather(directory_brands(request), official_brands(request))
    # A stale directory record cannot revive a revoked or unonboarded official business.
    return [b.model_copy(update={'sample': b.sample or official[b.organization_id].sample})
            for b in directory if b.organization_id in official]


async def brand(request, brand_id):
    found = next((b for b in await brands(request) if b.organization_id == brand_id), None)
    if found is None:
        raise PublicError("brand_unavailable", "Choose an onboarded brand offering customization.", status=409)
    return found


async def run(app, stop):
    dependencies = clients(app)
    try:
        relay = OutboxRelay(
            app.state.pool,
            {"communications": dependencies["communications"]},
            headers=lambda destination: {"Authorization": "Bearer " + os.getenv("BT_OPTIONS_EVENT_TOKEN", "")},
        )
        while not stop.is_set():
            # Without a service credential, intent remains durable instead of unauthenticated publication.
            if os.getenv("BT_OPTIONS_EVENT_TOKEN"):
                await relay.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass
    finally:
        for dependency in dependencies.values():
            await dependency.aclose()
