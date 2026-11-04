"""Identity-local fresh authority, sharing the Accounts row/session fence."""

from fastapi import HTTPException, Request
from bt_contracts_core.errors import AccessDenied
from bt_contracts_core.models import Actor
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import CurrentPrincipal, OrganizationGrant
from service_app.identity import live_actor


async def principal(request: Request) -> CurrentPrincipal:
    async with unit_of_work(request.app.state.pool) as tx:
        account, session = await live_actor(tx, request)
        rows = await tx.fetch(
            "SELECT * FROM identity_access_grants WHERE subject_id=$1 AND revoked_at IS NULL",
            account["id"],
        )
        permissions, roles, organizations = set(), {"buyer"}, {}
        for row in rows:
            roles.add(row["role"])
            if row["organization_id"] is None:
                permissions.update(row["permissions"])
            else:
                grant = organizations.setdefault(
                    row["organization_id"], {"permissions": set(), "roles": set()}
                )
                grant["permissions"].update(row["permissions"])
                grant["roles"].add(row["role"])
        return CurrentPrincipal(
            actor=Actor(
                subject_id=account["id"],
                session_id=str(session),
                organization_id=None,
            ),
            roles=sorted(roles),
            permissions=sorted(permissions),
            organizations=list(organizations),
            organization_grants=[
                OrganizationGrant(
                    organization_id=identity,
                    permissions=sorted(grant["permissions"]),
                    roles=sorted(grant["roles"]),
                )
                for identity, grant in organizations.items()
            ],
        )


async def require_current(tx, request, permission, subject):
    # Call after locking every affected account in UUID order. The second guard
    # prevents a formerly authorized command from resuming after suspension.
    account, session = await live_actor(tx, request, lock=True)
    if account["id"] != subject:
        raise HTTPException(401)
    granted = await tx.fetchval(
        """SELECT id FROM identity_access_grants WHERE subject_id=$1
        AND organization_id IS NULL AND revoked_at IS NULL AND $2=ANY(permissions) LIMIT 1""",
        subject,
        permission,
    )
    if not granted:
        raise AccessDenied("Current individual permission required")
    return account, session
