"""Bounded versioned peer adapters. No peer's failure can authorize a command."""
import os
import time
from uuid import UUID
import jwt
from fastapi import HTTPException, Request
from pydantic import ValidationError
from bt_bulkheads import Unavailable
from bt_runtime.principal import CurrentPrincipal, current_principal, require_scope
from bt_contracts_core.errors import AccessDenied, PublicError


async def principal(request: Request):
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    org = request.query_params.get('organization_id')
    if org:
        try:
            org = UUID(org)
        except ValueError:
            raise PublicError('invalid_organization', 'Select a valid organization.', status=422) from None
        data = await call(request, 'identity', 'GET', f'/internal/v1/principal?organization_id={org}')
        try:
            result = CurrentPrincipal.model_validate(data)
        except ValidationError:
            raise PublicError('identity_unavailable', 'Current access is unavailable.', status=503) from None
        if result.actor.organization_id != org:
            raise AccessDenied('Wrong represented organization')
    else:
        result = await current_principal(request.app.state.identity, token, request.state.request_id)
    if isinstance(result, Unavailable):
        raise PublicError('identity_unavailable', 'Current access is unavailable.', status=503)
    return result


def service_headers(request, audience):
    key = os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    if not key:
        raise PublicError('dependency_unavailable', 'Service authorization is unavailable.', status=503)
    now = int(time.time())
    token = jwt.encode({'sub': 'pricing', 'type': 'service', 'iss': request.app.state.settings.auth_issuer,
                        'aud': audience, 'iat': now, 'exp': now + 60}, key, algorithm='RS256')
    return {'Authorization': 'Bearer ' + token}


def service(request, allowed):
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise PublicError('dependency_unavailable', 'Service authorization is unavailable.', status=503)
    try:
        data = jwt.decode(token, settings.service_auth_public_key, algorithms=['RS256'],
            audience='pricing', issuer=settings.auth_issuer,
            options={'require': ['sub', 'type', 'iss', 'aud', 'iat', 'exp']})
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    if data['type'] != 'service' or data['sub'] not in allowed:
        raise AccessDenied('Wrong calling service')
    return data['sub']


async def call(request, name, method, path, *, internal=False, missing=False, **kwargs):
    headers = {'Authorization': request.headers.get('authorization', ''), 'X-Request-ID': request.state.request_id,
               **(service_headers(request, name) if internal else {}), **kwargs.pop('headers', {})}
    response = await getattr(request.app.state, name.replace('-', '_')).request(method, path, headers=headers, **kwargs)
    if isinstance(response, Unavailable) or response.status_code >= 500:
        raise PublicError('dependency_unavailable', 'A required service is unavailable. Retry the same operation.', status=503)
    if response.status_code == 404 and missing:
        return None
    if response.status_code == 401:
        raise HTTPException(401)
    if response.status_code == 403:
        raise AccessDenied('Current peer access refused')
    if response.status_code >= 300:
        raise PublicError('source_changed', 'Reload the current source and assessed scope.', status=409)
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        raise PublicError('dependency_unavailable', 'A required service is unavailable.', status=503) from None


async def listing(request, listing_id, revision):
    record = await call(request, 'catalog', 'GET', f'/v1/listings/{listing_id}/publication')
    try:
        if (UUID(record['id']) != listing_id or record['status'] != 'published'
                or type(record['revision']) is not int or record['revision'] != revision
                or record['facts']['sale_mode'] not in ('fixed_price', 'offer') or record['facts']['currency'] != 'USD'):
            raise PublicError('listing_changed', 'Review the current fixed-price or offers-only listing.', status=409)
        record['physical_watch_id'] = str(UUID(record['physical_watch_id']))
        record['seller_id'] = str(UUID(record['seller_id']))
        org = record.get('organization_id') or record.get('seller_organization_id')
        if org:
            org = str(UUID(org))
        record['organization_id'] = org
    except (KeyError, TypeError, ValueError):
        raise PublicError('dependency_unavailable', 'The listing cannot be verified.', status=503) from None
    return record


def seller(p, seller_id, organization_id):
    if organization_id:
        require_scope(p, 'identity.listings.publish', UUID(str(organization_id)))
    else:
        if p.actor.subject_id != UUID(str(seller_id)) or p.actor.organization_id is not None:
            raise AccessDenied('Not the actual seller')
        require_scope(p, 'identity.listings.publish')
