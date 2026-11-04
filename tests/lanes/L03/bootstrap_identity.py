"""Explicit isolated-proof initial principals; execute only inside Identity.

This is not a product route or seed verdict. Registrations use real Identity
commands, authority is confined to two labeled test principals in a generated
isolated database, and the Identity-local lock/audit/projection helpers are used.
All review decisions, official onboarding and membership must use actual APIs.
"""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
from bt_runtime.app.db import unit_of_work
from bt_runtime.modules import discover
from service_app.identity import lock_accounts


async def main():
    database = os.environ["BT_DATABASE_URL"]
    if (
        os.getenv("BT_SERVICE_NAME") != "identity"
        or os.getenv("BT_ENVIRONMENT") != "demo"
        or os.getenv("BT_L03_ISOLATED_BOOTSTRAP") != "isolated-principals-only"
        or not urlsplit(database).path.startswith("/bt_l03_identity_")
    ):
        raise SystemExit("Refused outside the explicitly authorized isolated Identity proof")
    actors = json.loads(Path("/proof/isolated-actors.key").read_text())
    security = next(m for m in discover(Path("/app/modules")) if m.id == "L01.accounts").load("security.py:audit")
    audit = security
    projection = security.__globals__["projection"]
    permissions = {
        "operator": ["identity.private-seller.assign", "identity.businesses.manage", "identity.membership.manage"],
        "reviewer": ["identity.private-seller.review"],
    }
    results = {}
    pool = await asyncpg.create_pool(database, min_size=1, max_size=2)
    try:
        for kind, capabilities in permissions.items():
            actor = actors[kind]
            if not actor["email"].startswith("l03-" + kind + "-") or not actor["email"].endswith("@example.test"):
                raise SystemExit("Only reserved, clearly labeled proof principals are allowed")
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:8000", headers={"Origin": "http://localhost:3077"}, timeout=10
            ) as client:
                answer = await client.post(
                    "/v1/accounts/login", json={"email": actor["email"], "password": actor["password"]}
                )
                if answer.status_code == 401:
                    answer = await client.post(
                        "/v1/accounts/register",
                        headers={"Idempotency-Key": "l03-bootstrap-" + kind},
                        json={**actor, "display_name": "Sample isolated " + kind},
                    )
                answer.raise_for_status()
                session = answer.json()
            subject = UUID(session["account"]["id"])
            async with unit_of_work(pool, lock_key="l03-isolated-bootstrap:" + str(subject)) as tx:
                await lock_accounts(tx, subject)
                account = await tx.fetchrow("SELECT * FROM identity_accounts WHERE id=$1", subject)
                if account["email"] != actor["email"] or account["display_name"] != "Sample isolated " + kind:
                    raise SystemExit("Refused to bootstrap an unrelated principal")
                existing = await tx.fetch(
                    "SELECT * FROM identity_access_grants WHERE subject_id=$1 AND revoked_at IS NULL", subject
                )
                if any(
                    g["organization_id"] is not None
                    or g["role"] != "operator"
                    or set(g["permissions"]) != set(capabilities)
                    for g in existing
                ):
                    raise SystemExit("Unexpected pre-existing authority; no changes made")
                if not existing:
                    await tx.execute(
                        "INSERT INTO identity_access_grants(id,subject_id,role,permissions) VALUES($1,$2,'operator',$3)",
                        uuid4(),
                        subject,
                        capabilities,
                    )
                    await tx.execute(
                        "UPDATE identity_accounts SET access_revision=access_revision+1 WHERE id=$1", subject
                    )
                await tx.execute(
                    "UPDATE identity_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE subject_id=$1", subject
                )
                request = SimpleNamespace(state=SimpleNamespace(request_id="l03-isolated-bootstrap"))
                await audit(tx, request, subject, subject, "sample.initial-principal", "authorized-isolated-proof")
                current = await projection(tx, account, uuid4())
                assert set(current.permissions) == set(capabilities)
                results[kind] = str(subject)
        print(json.dumps({"sample": True, "principals": results, "verdicts_seeded": False, "businesses_seeded": False}))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
