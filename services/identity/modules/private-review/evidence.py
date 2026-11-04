"""Same-domain, assigned-reviewer reads through the scoped-file adapter.

L01 owns identity_private_evidence and all uploads. L02 never writes its bytes.
"""

from uuid import UUID
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from bt_runtime.files import ScopedFiles
from bt_runtime.principal import CurrentPrincipal
from .security import principal, require_current

router = APIRouter(prefix="/v1/private-reviews", tags=["assigned-private-evidence"])
MAX_BYTES = 2 * 1024 * 1024


async def authorized_review(tx, actor, review_id):
    row = await tx.fetchrow(
        "SELECT * FROM l02_private_reviews WHERE id=$1 FOR SHARE", review_id
    )
    if (
        not row
        or row["reviewer_id"] != actor.actor.subject_id
        or row["applicant_id"] == actor.actor.subject_id
        or "identity.private-seller.review" not in actor.permissions
    ):
        raise AccessDenied("Current independent assignment required")
    return row


async def audit(tx, actor, review_id, evidence_id, outcome, request_id):
    await tx.execute(
        """INSERT INTO l02_review_evidence_audit(actor_id,review_id,evidence_id,outcome,request_id)
        VALUES($1,$2,$3,$4,$5)""",
        actor.actor.subject_id,
        review_id,
        evidence_id,
        outcome,
        request_id,
    )


@router.get("/{review_id}/evidence")
async def evidence_list(
    review_id: UUID, request: Request, actor: CurrentPrincipal = Depends(principal)
):
    denied = False
    async with unit_of_work(request.app.state.pool) as tx:
        try:
            await require_current(
                tx, request, "identity.private-seller.review", actor.actor.subject_id
            )
            review = await authorized_review(tx, actor, review_id)
        except AccessDenied:
            denied = True
        if not denied:
            rows = await tx.fetch(
                """SELECT id,kind,octet_length(content) AS size FROM identity_private_evidence
                WHERE application_id=$1 AND subject_id=$2 ORDER BY id LIMIT 12""",
                review["application_id"],
                review["applicant_id"],
            )
        await audit(
            tx,
            actor,
            review_id,
            None,
            "denied" if denied else "allowed",
            request.state.request_id,
        )
    if denied:
        raise AccessDenied("Current independent assignment required")
    return {
        "items": [
            {"id": str(row["id"]), "kind": row["kind"], "size": row["size"]}
            for row in rows
        ]
    }


class EvidenceStore:
    def __init__(self, tx, application_id, applicant_id):
        self.tx, self.application_id, self.applicant_id = (
            tx,
            application_id,
            applicant_id,
        )

    async def read(self, blob_id, *, max_bytes):
        content = await self.tx.fetchval(
            """SELECT content FROM identity_private_evidence WHERE id=$1
            AND application_id=$2 AND subject_id=$3 AND octet_length(content)<=$4""",
            blob_id,
            self.application_id,
            self.applicant_id,
            max_bytes,
        )
        if content is None:
            raise PublicError(
                "evidence_unavailable", "This private file is unavailable.", status=404
            )
        return content


@router.get("/{review_id}/files/{evidence_id}")
async def evidence_file(
    review_id: UUID,
    evidence_id: UUID,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
):
    failure = None
    async with unit_of_work(request.app.state.pool) as tx:
        try:
            await require_current(
                tx, request, "identity.private-seller.review", actor.actor.subject_id
            )
            review = await authorized_review(tx, actor, review_id)

            async def authorize(current, resource_id):
                # ScopedFiles never accepts a supplied path, URL or unrelated blob.
                if current.actor.subject_id != review["reviewer_id"]:
                    raise AccessDenied("Assignment changed")
                return resource_id

            files = ScopedFiles(
                EvidenceStore(tx, review["application_id"], review["applicant_id"]),
                authorize,
                max_bytes=MAX_BYTES,
            )
            content = await files.read(actor, evidence_id)
        except (AccessDenied, PublicError) as error:
            failure = error
        await audit(
            tx,
            actor,
            review_id,
            evidence_id,
            "denied" if failure else "allowed",
            request.state.request_id,
        )
    # Denial audit survives the failed read. No proof bytes enter logs/previews.
    if failure:
        raise failure
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="private-verification-evidence"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
