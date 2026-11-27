"""Confined initial sample principal, executed only inside isolated Identity.

Business onboarding and membership still use real authorized HTTP commands.
No review, approval, payment, inspection, receipt or completion is seeded.
"""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
from bt_runtime.app.db import unit_of_work
from bt_runtime.modules import discover
from service_app.identity import lock_accounts


async def main():
    database = os.environ["BT_DATABASE_URL"]
    if (
        os.getenv("BT_SERVICE_NAME") != "identity"
        or os.getenv("BT_ENVIRONMENT") != "demo"
        or not urlsplit(database).path.startswith("/bt_l15_identity_")
    ):
        raise SystemExit("Refused outside isolated Identity proof")
    metadata = json.loads(Path("/proof/actors.key").read_text())["operator"]
    if not metadata["email"].startswith("l15-operator-") or not metadata[
        "email"
    ].endswith("@example.test"):
        raise SystemExit("Only the reserved sample principal is eligible")
    subject = UUID(metadata["id"])
    audit = next(
        module
        for module in discover(Path("/app/modules"))
        if module.id == "L01.accounts"
    ).load("security.py:audit")
    permissions = ["identity.businesses.manage", "identity.membership.manage"]
    pool = await asyncpg.create_pool(database, min_size=1, max_size=2)
    try:
        async with unit_of_work(
            pool, lock_key="l15-isolated-bootstrap:" + str(subject)
        ) as tx:
            await lock_accounts(tx, subject)
            account = await tx.fetchrow(
                "SELECT * FROM identity_accounts WHERE id=$1", subject
            )
            if (
                not account
                or account["email"] != metadata["email"]
                or account["display_name"] != "Sample isolated operator"
            ):
                raise SystemExit("Unrelated principal refused")
            grants = await tx.fetch(
                "SELECT * FROM identity_access_grants WHERE subject_id=$1 AND revoked_at IS NULL",
                subject,
            )
            if grants:
                raise SystemExit(
                    "Initial principal already has authority; no change made"
                )
            await tx.execute(
                "INSERT INTO identity_access_grants(id,subject_id,role,permissions) VALUES($1,$2,'operator',$3)",
                uuid4(),
                subject,
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
            await audit(
                tx,
                SimpleNamespace(
                    state=SimpleNamespace(request_id="l15-isolated-bootstrap")
                ),
                subject,
                subject,
                "sample.initial-principal",
                "isolated-proof",
            )
        print("Initial sample principal ready; no business outcome seeded")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
