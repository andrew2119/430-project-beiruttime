"""Authorized same-domain capability write seam; caller owns the transaction."""

from uuid import uuid4
from bt_contracts_core.errors import PublicError


async def sync_member(tx, member, kind):
    subject = member["subject_id"]
    account = await tx.fetchrow(
        "SELECT id,status FROM identity_accounts WHERE id=$1", subject
    )
    if member["state"] == "active" and (not account or account["status"] != "active"):
        raise PublicError(
            "account_unavailable", "An active colleague is required.", status=409
        )
    await tx.execute(
        """UPDATE identity_access_grants SET revoked_at=coalesce(revoked_at,now())
        WHERE subject_id=$1 AND organization_id=$2 AND role IN ('dealer','brand')""",
        subject,
        member["business_id"],
    )
    if member["state"] == "active":
        permissions = list(member["capabilities"])
        if "business.stock.write" in permissions:
            permissions.append("identity.listings.publish")
        await tx.execute(
            """INSERT INTO identity_access_grants(id,subject_id,organization_id,role,permissions)
            VALUES($1,$2,$3,$4,$5)""",
            uuid4(),
            subject,
            member["business_id"],
            kind,
            permissions,
        )
    await tx.execute(
        "UPDATE identity_accounts SET access_revision=access_revision+1 WHERE id=$1",
        subject,
    )
    await tx.execute(
        "UPDATE identity_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE subject_id=$1",
        subject,
    )
