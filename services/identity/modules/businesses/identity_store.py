"""Business assurance and organization capabilities change in one Identity UoW."""

from uuid import uuid4


async def affected_subjects(tx, business_id):
    rows = await tx.fetch(
        """SELECT subject_id FROM l02_memberships WHERE business_id=$1
        UNION SELECT subject_id FROM identity_access_grants WHERE organization_id=$1""",
        business_id,
    )
    return [row["subject_id"] for row in rows]


async def sync_business(tx, business):
    subjects = await affected_subjects(tx, business["id"])
    await tx.execute(
        """UPDATE identity_access_grants SET revoked_at=coalesce(revoked_at,now())
        WHERE organization_id=$1""",
        business["id"],
    )
    if business["state"] == "active":
        members = await tx.fetch(
            """SELECT m.* FROM l02_memberships m JOIN identity_accounts a ON a.id=m.subject_id
            WHERE m.business_id=$1 AND m.state='active' AND a.status='active' """,
            business["id"],
        )
        for member in members:
            permissions = list(member["capabilities"])
            if "business.stock.write" in permissions:
                permissions.append("identity.listings.publish")
            await tx.execute(
                """INSERT INTO identity_access_grants(id,subject_id,organization_id,role,permissions)
                VALUES($1,$2,$3,$4,$5)""",
                uuid4(),
                member["subject_id"],
                business["id"],
                business["kind"],
                permissions,
            )
    for subject in subjects:
        await tx.execute(
            "UPDATE identity_accounts SET access_revision=access_revision+1 WHERE id=$1",
            subject,
        )
        await tx.execute(
            "UPDATE identity_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE subject_id=$1",
            subject,
        )
