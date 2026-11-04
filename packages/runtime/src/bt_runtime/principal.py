"""Fresh identity/org decisions over an authenticated bounded dependency."""
from uuid import UUID
from pydantic import Field
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.models import Actor, Contract
from bt_contracts_core.errors import AccessDenied


class OrganizationGrant(Contract):
    organization_id: UUID
    permissions: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class CurrentPrincipal(Contract):
    actor: Actor
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    organizations: list[UUID] = Field(default_factory=list)
    organization_grants: list[OrganizationGrant] = Field(default_factory=list)


async def current_principal(identity: DependencyClient, token: str, request_id: str) -> CurrentPrincipal | Unavailable:
    response = await identity.request('GET', '/internal/v1/principal', headers={
        'Authorization': 'Bearer ' + token, 'X-Request-ID': request_id})
    if isinstance(response, Unavailable):
        return response
    if response.status_code != 200:
        raise AccessDenied('Current identity could not be established')
    return CurrentPrincipal.model_validate(response.json())


def require_scope(principal: CurrentPrincipal, permission: str, organization_id: UUID | None = None) -> None:
    if organization_id is None:
        allowed = permission in principal.permissions
    else:
        allowed = (principal.actor.organization_id == organization_id
            and organization_id in principal.organizations
            and any(grant.organization_id == organization_id and permission in grant.permissions
                    for grant in principal.organization_grants))
    if not allowed:
        raise AccessDenied('Permission or organization scope denied')
