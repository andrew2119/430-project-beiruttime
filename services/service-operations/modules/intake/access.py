"""Assigned-record checks using the current authority provider."""
import asyncio
from uuid import UUID

from fastapi import HTTPException
from bt_bulkheads import Unavailable
from bt_runtime.principal import require_scope
from .dependencies import bearer, clients
from .current_provider import CurrentAuthority
from bt_contracts.service.intake.current import RecordAccess, RecordListAccess


async def organization(p, request, permission):
    org = p.actor.organization_id
    if org is None:
        raise HTTPException(403)
    canonical = {'intake.read': 'business.records.read', 'intake.write': 'business.jobs.write'}[permission]
    legacy = any(grant.organization_id == org and permission in grant.permissions
                 for grant in p.organization_grants)
    require_scope(p, permission if legacy else canonical, org)
    response = await clients(request.app)['service-operations'].request(
        'GET', f'/v1/directory/providers/{org}', headers={'Authorization': 'Bearer ' + bearer(request)})
    if isinstance(response, Unavailable) or response.status_code not in (200, 401, 403, 404, 409):
        raise HTTPException(503)
    if response.status_code == 401:
        raise HTTPException(401)
    if response.status_code != 200:
        raise HTTPException(403)
    try:
        provider = response.json()
        valid = (UUID(str(provider['organization_id'])) == org and provider['official'] is True
                 and provider['active'] is True and provider['kind'] in ('brand', 'dealer'))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503) from None
    if not valid:
        raise HTTPException(403)
    return org


def assignment_unavailable():
    return HTTPException(503, detail='intake_assignment_unavailable')


def assignment_provider(request, operation):
    state = request.app.state
    provider = getattr(state, 'intake_assignments', None)
    if provider is not None:
        return provider
    authority = getattr(state, 'intake_current_authority', None)
    if callable(getattr(authority, operation, None)):
        return authority
    return CurrentAuthority(request)


async def assignment_facts(request, operation, schema, *binding):
    provider = assignment_provider(request, operation)
    check = getattr(provider, operation, None)
    if not callable(check):
        raise assignment_unavailable()
    try:
        return schema.model_validate(await asyncio.wait_for(check(*binding), timeout=1.2))
    except HTTPException as error:
        if error.status_code in (401, 403):
            raise
        raise assignment_unavailable() from None
    except (OSError, ValueError):
        raise assignment_unavailable() from None


async def record_access(p, request, org, order_id, permission):
    value = await assignment_facts(request, 'record_access', RecordAccess,
                                   p.actor.subject_id, org, order_id, permission)
    if (value.actor_id, value.organization_id, value.order_id, value.permission, value.allowed) != (
            p.actor.subject_id, org, order_id, permission, True):
        raise HTTPException(403)
    return value


async def require_private_assignment(p, request, org, order_id, permission):
    """Keep absent and unassigned private resources indistinguishable."""
    try:
        return await record_access(p, request, org, order_id, permission)
    except HTTPException as error:
        if error.status_code == 403:
            raise HTTPException(404) from None
        raise


async def readable_orders(p, request, org):
    value = await assignment_facts(request, 'readable_orders', RecordListAccess,
                                   p.actor.subject_id, org)
    if (value.actor_id, value.organization_id) != (p.actor.subject_id, org):
        raise HTTPException(403)
    return value.order_ids
