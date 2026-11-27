"""Catalog's immutable request repository and current authorization boundary."""

import json
import jwt
from fastapi import HTTPException
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import require_scope
from service_app.catalog_dependencies import principal, upstream


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


async def active_brand(request, brand_id):
    brand = await upstream(request, "identity", "GET", f"/v1/businesses/{brand_id}")
    if not isinstance(brand, dict) or brand.get("id") != str(brand_id):
        raise PublicError("brand_unavailable", "The current brand cannot be confirmed.", status=503)
    if not (
        brand.get("kind") == "brand"
        and brand.get("state") == "active"
        and brand.get("platform_onboarded") is True
        and brand.get("authenticated_business") is True
        and "customization" in brand.get("capabilities", [])
    ):
        raise AccessDenied("An active onboarded customization brand is required")
    return brand


def service(request, allowed, *, header="Authorization"):
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise PublicError("service_unavailable", "Service authorization is unavailable.", status=503)
    scheme, _, token = request.headers.get(header, "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192:
        raise HTTPException(401)
    try:
        claims = jwt.decode(
            token,
            settings.service_auth_public_key,
            algorithms=["RS256"],
            issuer=settings.auth_issuer,
            audience="catalog",
            options={"require": ["exp", "iat", "iss", "aud", "sub", "type"]},
        )
        if claims["type"] != "service" or claims["sub"] not in allowed:
            raise AccessDenied("Wrong service scope")
        return claims["sub"]
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None


async def current(tx, request_id, *, lock=False):
    row = await tx.fetchrow(
        "SELECT * FROM catalog_customization_requests WHERE id=$1" + (" FOR UPDATE" if lock else ""), request_id
    )
    if row is None:
        raise PublicError("not_found", "Request not found.", status=404)
    rev = await tx.fetchrow(
        "SELECT * FROM catalog_customization_revisions WHERE request_id=$1 AND revision=$2", request_id, row["revision"]
    )
    return row, rev


def view(row, rev, *, internal=False):
    configuration = decode(rev["configuration"])
    content = decode(rev["content"])
    if internal:
        configuration = {k: v for k, v in configuration.items() if k != "reference_ids"}
        content = {"watch_context": content["watch_context"]}
    return {
        **content,
        "id": str(row["id"]),
        "draft_id": str(row["draft_id"]),
        "revision": row["revision"],
        "buyer_id": str(row["buyer_id"]),
        "brand_id": str(row["brand_id"]),
        "status": "submitted",
        "configuration_digest": rev["configuration_digest"],
        "configuration": configuration,
        "created_at": rev["created_at"].isoformat(),
    }


async def readable(request, row, person=None):
    person = person or await principal(request)
    if person.actor.subject_id == row["buyer_id"] and person.actor.organization_id is None:
        return person
    require_scope(person, "business.jobs.write", row["brand_id"])
    await active_brand(request, row["brand_id"])
    return person
