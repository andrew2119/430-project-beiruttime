"""Per-upstream bulkheads. No fixture transport is enabled in the runtime."""

import os
import asyncio
import time
import jwt
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError
from uuid import UUID
from bt_runtime.principal import CurrentPrincipal, current_principal, require_scope


def clients(app):
    if not hasattr(app.state, "catalog_clients"):
        app.state.catalog_clients = {
            name: DependencyClient(
                name, os.getenv(f"BT_{name.upper().replace('-', '_')}_URL", os.getenv(f"{name.upper().replace('-', '_')}_URL", f"http://{name}:8000")), timeout=2.5, concurrency=4
            )
            for name in ("identity", "pricing", "orders", "auction", "communications", "trust", "service-operations", "eligibility")
        }
    return app.state.catalog_clients


async def manage_clients(app, stop):
    owned = clients(app)
    try:
        await stop.wait()
    finally:
        await asyncio.gather(*(client.aclose() for client in owned.values()))


async def principal(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or len(auth) > 8192:
        raise PublicError("unauthorized", "Sign in to continue.", status=401)
    selected = request.query_params.get("organization_id")
    if selected:
        try:
            selected = str(UUID(selected))
        except ValueError:
            raise PublicError("invalid_organization", "Choose a valid organization.", status=422) from None
        response = await clients(request.app)["identity"].request(
            "GET",
            "/internal/v1/principal",
            params={"organization_id": selected},
            headers={"Authorization": auth, "X-Request-ID": request.state.request_id},
        )
        if isinstance(response, Unavailable):
            result = response
        else:
            if response.status_code == 401:
                raise PublicError("unauthorized", "Sign in to continue.", status=401)
            if response.status_code != 200:
                raise AccessDenied("Current organization could not be established")
            result = CurrentPrincipal.model_validate(response.json())
            if str(result.actor.organization_id) != selected:
                raise AccessDenied("Organization selection differs")
    else:
        result = await current_principal(clients(request.app)["identity"], auth[7:], request.state.request_id)
    if isinstance(result, Unavailable):
        raise PublicError("identity_unavailable", "Identity is temporarily unavailable.", status=503)
    return result


def seller_scope(person, permission=None):
    org = person.actor.organization_id
    if org:
        require_scope(person, "business.stock.write", org)
        if permission:
            require_scope(person, permission, org)
        # Resolve official kind from Identity's public business DTO, not a job title.
        return None
    # Any signed-in individual may prepare a private draft; publication alone
    # requires current private-seller approval from Identity.
    if permission:
        require_scope(person, permission)
    return "private"


def assert_owner(row, person):
    if row is None:
        raise PublicError("not_found", "Listing not found.", status=404)
    if row["organization_id"]:
        if row["organization_id"] != person.actor.organization_id:
            raise AccessDenied("Organization scope differs")
        require_scope(person, "business.stock.write", row["organization_id"])
    elif row["owner_subject_id"] != person.actor.subject_id or person.actor.organization_id:
        raise AccessDenied("Listing ownership differs")


async def service_request(request, dependency, method, path, **kwargs):
    signing = os.getenv("BT_SERVICE_AUTH_PRIVATE_KEY")
    if not signing:
        raise PublicError(
            f"{dependency}_unavailable",
            "A required service is temporarily unavailable. Retry this operation.",
            status=503,
        )
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "catalog",
            "type": "service",
            "iss": request.app.state.settings.auth_issuer,
            "aud": dependency,
            "iat": now,
            "exp": now + 60,
        },
        signing,
        algorithm="RS256",
    )
    return await upstream(
        request,
        dependency,
        method,
        path,
        headers={"Authorization": "Bearer " + token, **kwargs.pop("headers", {})},
        **kwargs,
    )


async def upstream(request, dependency, method, path, **kwargs):
    # Pricing quotes belong to the acting human's personal context, even when
    # that human is preparing an authorized organization's listing.
    if dependency != "pricing" and request.query_params.get("organization_id"):
        kwargs.setdefault("params", {"organization_id": request.query_params["organization_id"]})
    result = await clients(request.app)[dependency].request(
        method,
        path,
        headers={
            "Authorization": request.headers.get("Authorization", ""),
            "X-Request-ID": request.state.request_id,
            **kwargs.pop("headers", {}),
        },
        **kwargs,
    )
    if isinstance(result, Unavailable):
        raise PublicError(
            f"{dependency}_unavailable",
            "A required service is temporarily unavailable. Retry this operation.",
            status=503,
        )
    if result.status_code == 401:
        raise PublicError("unauthorized", "Sign in to continue.", status=401)
    if result.status_code == 403:
        raise AccessDenied("Upstream denied current scope")
    if result.status_code >= 500:
        raise PublicError(f"{dependency}_unavailable", "A required service is temporarily unavailable.", status=503)
    if result.status_code >= 400:
        raise PublicError(f"{dependency}_denied", "A required prerequisite was not accepted.", status=409)
    try:
        return result.json()
    except ValueError:
        raise PublicError(
            f"{dependency}_unavailable", "A required service returned an invalid response.", status=503
        ) from None
