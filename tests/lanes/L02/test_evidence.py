import hashlib
from uuid import UUID, uuid4
import asyncpg
import pytest
from test_identity_modules import key


@pytest.mark.asyncio
async def test_private_files_are_assigned_bounded_and_denials_are_audited(
    api, database_owner_url
):
    client, state, pool, _ = api
    application = uuid4()
    review = (
        await client.post(
            "/v1/private-reviews",
            json={
                "application_id": str(application),
                "reviewer_id": str(state["reviewer"]),
                "reason": "Independent review assigned",
            },
            headers=key(),
        )
    ).json()["id"]
    # Frozen L01 evidence-store fixture; production uses L01's actual migration.
    owner = await asyncpg.connect(database_owner_url)
    evidence, unrelated = uuid4(), uuid4()
    content = b"Sample possession evidence, not a real identity document"
    try:
        await owner.execute("""CREATE TABLE IF NOT EXISTS identity_private_evidence(
            id uuid PRIMARY KEY,application_id uuid NOT NULL,subject_id uuid NOT NULL,
            kind text NOT NULL,content bytea NOT NULL,sha256 text NOT NULL,created_at timestamptz DEFAULT now())""")
        other_application = uuid4()
        await owner.execute(
            """INSERT INTO identity_private_applications(id,subject_id,revision,status,identity_name,contact,payout_reference)
            VALUES($1,$2,1,'pending','Other sample individual','Private sample contact','DEMO-OTHER')""",
            other_application,
            state["outsider"],
        )
        for identity, case, size in [
            (evidence, application, content),
            (unrelated, other_application, b"Other private application"),
        ]:
            await owner.execute(
                """INSERT INTO identity_private_evidence(id,application_id,subject_id,kind,content,sha256)
                VALUES($1,$2,$3,'possession',$4,$5)""",
                identity,
                case,
                state["applicant"] if case == application else state["outsider"],
                size,
                hashlib.sha256(size).hexdigest(),
            )
    finally:
        await owner.close()
    state["actor"] = state["outsider"]
    assert (
        await client.get(f"/v1/private-reviews/{review}/evidence")
    ).status_code == 403
    assert (
        await client.get(f"/v1/private-reviews/{review}/files/{evidence}")
    ).status_code == 403
    state["actor"] = state["reviewer"]
    records = (await client.get(f"/v1/private-reviews/{review}/evidence")).json()[
        "items"
    ]
    assert {"id": str(evidence), "kind": "possession", "size": len(content)} in records
    assert not any(row["id"] == str(unrelated) for row in records)
    response = await client.get(f"/v1/private-reviews/{review}/files/{evidence}")
    assert response.status_code == 200
    assert response.content == content
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert (
        await client.get(f"/v1/private-reviews/{review}/files/{unrelated}")
    ).status_code == 404
    async with pool.acquire() as tx:
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM l02_review_evidence_audit WHERE outcome='denied'"
            )
            == 3
        )
        assert (
            await tx.fetchval(
                "SELECT count(*) FROM l02_review_evidence_audit WHERE review_id=$1",
                UUID(review),
            )
            == 5
        )
