"""Request-scoped ownership, destination and private-reference authority."""
from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, TypeAdapter

from fastapi import HTTPException
from bt_bulkheads import Unavailable
from bt_contracts.service.maintenance.v1 import AdmissionAuthority, Context, RequestAuthority
from bt_runtime.principal import CurrentPrincipal, current_principal
from service_app.sources import bearer, client, prerequisite
from .photos import photo_scope


async def identity(request, organization=None):
    upstream = client(request, 'identity')
    token = bearer(request)
    try:
        if organization is None:
            value = await current_principal(upstream, token, request.state.request_id)
            if isinstance(value, Unavailable):
                raise HTTPException(503)
            return value
        response = await upstream.request('GET', f'/internal/v1/principal?organization_id={organization}',
            headers={'Authorization': 'Bearer ' + token, 'X-Request-ID': request.state.request_id})
        if isinstance(response, Unavailable):
            raise HTTPException(503)
        if response.status_code in (401, 403):
            raise HTTPException(response.status_code)
        if response.status_code != 200:
            raise HTTPException(503)
        value = CurrentPrincipal.model_validate(response.json())
    except (ValueError, OSError):
        raise HTTPException(503) from None
    if value.actor.organization_id != organization or organization not in value.organizations:
        raise HTTPException(403)
    return value


async def buyer_identity(request):
    value = await identity(request)
    if value.actor.organization_id is not None or 'buyer' not in value.roles:
        raise HTTPException(403)
    return value.actor.subject_id


class Provider:
    def __init__(self, request):
        self.request = request

    async def context(self, actor, watch, brand=None):
        facts = Context.model_validate(await prerequisite(self.request, 'maintenance_context', actor, watch, brand))
        if (facts.actor_id, facts.subject_id, facts.watch_id) != (actor, actor, watch):
            raise HTTPException(403)
        return facts

    async def admission(self, actor, watch, organization, operation, intervention, brand):
        return AdmissionAuthority.model_validate(await prerequisite(
            self.request, 'maintenance_admission', actor, watch, organization, operation, intervention, brand))

    async def current_with_photos(self, body, tx):
        facts = await self.admission(body.actor_id, body.watch_id, body.organization_id,
                                     body.operation_id, body.intervention, body.brand_id)
        refs = set(body.photo_refs)
        if refs:
            rows = await tx.fetch('''SELECT photo_ref FROM maintenance_request_photos
                WHERE actor_id=$1 AND watch_id=$2 AND organization_id=$3 AND request_operation_id=$4
                  AND photo_ref=ANY($5::uuid[]) AND content IS NOT NULL
                  AND (request_id IS NOT NULL OR expires_at > statement_timestamp())
                  AND (brand_id, intervention, watch_revision, capability_revision, policy_revision)
                    = ($6,$7,$8,$9,$10)''', body.actor_id, body.watch_id, body.organization_id,
                body.operation_id, body.photo_refs, *photo_scope(body))
            refs.difference_update(row['photo_ref'] for row in rows)
        return RequestAuthority(**facts.model_dump(), private_refs_current=not refs)

    async def operation_access(self, actor, organization, operation, watch=None, intervention=None, brand=None):
        if watch is None:
            # Closing a missing receipt creates a tombstone only for this buyer and organization.
            return True
        from bt_contracts.service.maintenance.staff import HistoricalOwner
        facts = HistoricalOwner.model_validate(await prerequisite(self.request, 'maintenance_historical_owner', actor, watch))
        return (facts.actor_id, facts.watch_id, facts.title_holder_id, facts.owned) == (actor, watch, actor, True)

    async def staff_authority(self, name, *binding):
        try:
            return await prerequisite(self.request, name, *binding)
        except KeyError:
            raise ConnectionError('maintenance_assignment_unavailable') from None

    async def assessment_queue_access(self, actor, organization):
        from .staff import queue_access
        return await queue_access(self.request, actor, organization)

    async def assessment_access(self, actor, organization, request_id, tx):
        from .staff import assignment_access
        return await assignment_access(self.request, actor, organization, request_id, tx)

    async def delivery_recovery_access(self, actor):
        data = await self.staff_authority('maintenance_delivery_recovery_access', actor)
        try:
            return UUID(data['actor_id']) == actor and data['allowed'] is True
        except (ValueError, TypeError, KeyError):
            raise ConnectionError('maintenance_recovery_unavailable') from None

    async def delivery_authority_until(self, actor) -> datetime | None:
        data = await self.staff_authority('maintenance_delivery_recovery_access', actor)
        try:
            if UUID(data['actor_id']) != actor or type(data['allowed']) is not bool:
                raise ValueError('recovery_scope')
            if data['allowed'] is False:
                return None
            return TypeAdapter(AwareDatetime).validate_python(data['held_until'])
        except (ValueError, TypeError, KeyError):
            raise ConnectionError('maintenance_recovery_unavailable') from None
