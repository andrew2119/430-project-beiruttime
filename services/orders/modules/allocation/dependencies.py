import os
from datetime import datetime, timezone, timedelta
from uuid import UUID
import jwt
from fastapi import HTTPException, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import current_principal, CurrentPrincipal
from bt_contracts.orders.allocation import ValidatedQuote


def clients(app):
    if not hasattr(app.state, "allocation_clients"):
        app.state.allocation_clients = {
            name: DependencyClient(
                name,
                os.environ.get("BT_" + name.upper() + "_URL", "http://" + name + ":8000"),
                timeout=1.2,
                concurrency=4,
            )
            for name in ("identity", "pricing", "catalog", "communications")
        }
    return app.state.allocation_clients


async def principal(request: Request):
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192:
        raise HTTPException(401)
    organization = request.query_params.get("organization_id")
    if organization:
        try:
            organization = UUID(organization)
        except ValueError:
            raise PublicError("invalid_organization", "Choose a valid organization.", status=422) from None
    try:
        if organization:
            response = await clients(request.app)["identity"].request(
                "GET",
                f"/internal/v1/principal?organization_id={organization}",
                headers={"Authorization": "Bearer " + token, "X-Request-ID": request.state.request_id},
            )
            if isinstance(response, Unavailable):
                value = response
            elif response.status_code == 401:
                raise HTTPException(401)
            elif response.status_code >= 500:
                raise PublicError(
                    "identity_unavailable", "Current organization permissions are unavailable.", status=503
                )
            elif response.status_code != 200:
                raise AccessDenied("Current organization could not be established")
            else:
                value = CurrentPrincipal.model_validate(response.json())
        else:
            value = await current_principal(clients(request.app)["identity"], token, request.state.request_id)
    except (ValueError, TypeError):
        raise PublicError("identity_unavailable", "Current permissions are unavailable.", status=503) from None
    if isinstance(value, Unavailable):
        raise PublicError("identity_unavailable", "Current permissions are unavailable.", status=503)
    return value


def service(request: Request, expected: str | set[str]):
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise HTTPException(503)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192:
        raise HTTPException(401)
    try:
        claims = jwt.decode(
            token,
            settings.service_auth_public_key,
            algorithms=["RS256"],
            issuer=settings.auth_issuer,
            audience="orders",
            options={"require": ["exp", "iat", "iss", "aud", "sub", "type"]},
        )
        allowed = {expected} if isinstance(expected, str) else expected
        if claims["type"] != "service" or claims["sub"] not in allowed:
            raise AccessDenied("Wrong service scope")
        return claims["sub"]
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None


async def organization_principal(request: Request, organization_id: UUID):
    response = await clients(request.app)["identity"].request(
        "GET",
        f"/internal/v1/principal?organization_id={organization_id}",
        headers={"Authorization": request.headers["Authorization"], "X-Request-ID": request.state.request_id},
    )
    if isinstance(response, Unavailable):
        raise PublicError("identity_unavailable", "Current organization permissions are unavailable.", status=503)
    if response.status_code == 401:
        raise HTTPException(401)
    if response.status_code >= 500:
        raise PublicError("identity_unavailable", "Current organization permissions are unavailable.", status=503)
    if response.status_code != 200:
        raise AccessDenied("Current organization denied")
    try:
        return CurrentPrincipal.model_validate(response.json())
    except (ValueError, TypeError):
        raise PublicError(
            "identity_unavailable", "Current organization permissions are unavailable.", status=503
        ) from None


async def quote(request: Request, quote_id):
    response = await clients(request.app)["pricing"].request(
        "GET",
        f"/internal/v1/quotes/{quote_id}/validation",
        headers={"Authorization": request.headers["Authorization"], "X-Request-ID": request.state.request_id},
    )
    if isinstance(response, Unavailable):
        raise PublicError("pricing_unavailable", "The quote cannot be confirmed. Retry the same operation.", status=503)
    if response.status_code == 401:
        raise HTTPException(401)
    if response.status_code in (400, 403, 404, 409, 410, 422):
        raise PublicError("quote_invalid", "A current quote belonging to this buyer is required.", status=409)
    try:
        if response.status_code != 200:
            raise ValueError()
        return ValidatedQuote.model_validate(response.json())
    except (ValueError, TypeError):
        raise PublicError("pricing_unavailable", "The quote cannot be confirmed.", status=503) from None


def delivery_headers(destination):
    private_key = os.environ.get("BT_SERVICE_AUTH_PRIVATE_KEY", "")
    if not private_key:
        raise RuntimeError("Service signing is not configured")
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "orders",
            "type": "service",
            "iss": os.environ.get("BT_AUTH_ISSUER", "beirut-time-identity"),
            "aud": destination,
            "iat": now,
            "exp": now + timedelta(seconds=60),
        },
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": "Bearer " + token}
