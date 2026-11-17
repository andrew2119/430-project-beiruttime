import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field, field_validator
from bt_contracts_core.models import Contract, EventEnvelope
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import CurrentPrincipal, require_scope
from service_app.identity import live_actor, lock_accounts
from .security import principal, require_current

router = APIRouter(prefix="/v1/private-reviews", tags=["private-seller-review"])


class Reasoned(Contract):
    @field_validator("reason", check_fields=False)
    @classmethod
    def meaningful(cls, value):
        value = value.strip()
        if len(value) < 5:
            raise ValueError("A meaningful decision reason is required")
        return value


class Assign(Reasoned):
    application_id: UUID
    reviewer_id: UUID
    reason: str = Field(min_length=5, max_length=500)


class Verdict(Reasoned):
    revision: int = Field(ge=1)
    application_revision: int = Field(ge=1)
    state: Literal["correction", "approved", "rejected", "suspended"]
    reason: str = Field(min_length=5, max_length=500)


class Reassign(Reasoned):
    revision: int = Field(ge=1)
    reviewer_id: UUID
    reason: str = Field(min_length=5, max_length=500)


def dto(row):
    return {
        key: str(row[key]) if key.endswith("_id") or key == "id" else row[key]
        for key in (
            "id",
            "application_id",
            "applicant_id",
            "reviewer_id",
            "application_revision",
            "state",
            "revision",
        )
    }


async def application(tx, application_id, *, lock=False):
    row = await tx.fetchrow(
        "SELECT * FROM identity_private_applications WHERE id=$1"
        + (" FOR UPDATE" if lock else ""),
        application_id,
    )
    if not row:
        raise AccessDenied(
            "A private application is required; business records are not applications"
        )
    kinds = await tx.fetch(
        "SELECT DISTINCT kind FROM identity_private_evidence WHERE application_id=$1 AND subject_id=$2",
        application_id,
        row["subject_id"],
    )
    return {
        **dict(row),
        "complete": bool(
            row["identity_name"].strip()
            and row["contact"].strip()
            and row["payout_reference"].startswith("DEMO-")
            and {item["kind"] for item in kinds} == {"identity", "possession"}
        ),
    }


async def qualified_reviewer(tx, reviewer, applicant):
    if reviewer == applicant:
        raise AccessDenied("Self-review denied")
    allowed = await tx.fetchval(
        """SELECT a.id FROM identity_accounts a JOIN identity_access_grants g ON g.subject_id=a.id
        WHERE a.id=$1 AND a.status='active' AND g.organization_id IS NULL AND g.revoked_at IS NULL
        AND 'identity.private-seller.review'=ANY(g.permissions) LIMIT 1""",
        reviewer,
    )
    if not allowed:
        raise AccessDenied("A currently qualified reviewer is required")


async def assignment(tx, application_id, reviewer):
    await tx.execute(
        "UPDATE identity_private_assignments SET revoked_at=now() WHERE application_id=$1 AND revoked_at IS NULL",
        application_id,
    )
    await tx.execute(
        """INSERT INTO identity_private_assignments(application_id,reviewer_id) VALUES($1,$2)
        ON CONFLICT(application_id,reviewer_id) DO UPDATE SET revoked_at=NULL""",
        application_id,
        reviewer,
    )


async def previous(tx, actor, key, fingerprint):
    old = await tx.fetchrow(
        "SELECT * FROM l02_private_review_operations WHERE actor_id=$1 AND operation_key=$2",
        actor,
        key,
    )
    if old:
        if old["fingerprint"] != fingerprint:
            raise PublicError(
                "idempotency_conflict", "Operation key already used.", status=409
            )
        return json.loads(old["result"])


async def record(tx, request, actor, key, fingerprint, row, reason, event_type):
    await tx.execute(
        """INSERT INTO l02_private_review_history(review_id,actor_id,revision,state,reason)
        VALUES($1,$2,$3,$4,$5)""",
        row["id"],
        actor,
        row["revision"],
        row["state"],
        reason,
    )
    result = dto(row)
    await tx.execute(
        "INSERT INTO l02_private_review_operations VALUES($1,$2,$3,$4::jsonb)",
        actor,
        key,
        fingerprint,
        json.dumps(result),
    )
    await enqueue(
        tx,
        EventEnvelope(
            type=event_type,
            source="identity",
            subject=str(row["applicant_id"]),
            request_id=request.state.request_id,
            data={
                "subject_id": str(row["applicant_id"]),
                "review_id": str(row["id"]),
                "application_id": str(row["application_id"]),
                "application_revision": row["application_revision"],
                "revision": row["revision"],
                "state": row["state"],
                "reviewer_id": str(row["reviewer_id"]),
            },
        ),
        ["communications"]
        if event_type == "identity.private-review-assigned.v1"
        else ["catalog", "communications"],
    )
    return result


@router.get("")
async def queue(request: Request, actor: CurrentPrincipal = Depends(principal)):
    require_scope(actor, "identity.private-seller.review")
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch(
            "SELECT * FROM l02_private_reviews WHERE reviewer_id=$1 ORDER BY updated_at DESC LIMIT 100",
            actor.actor.subject_id,
        )
    return {"items": [dto(row) for row in rows]}


@router.get("/mine")
async def mine(request: Request, actor: CurrentPrincipal = Depends(principal)):
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch(
            "SELECT * FROM l02_private_reviews WHERE applicant_id=$1 ORDER BY updated_at DESC LIMIT 100",
            actor.actor.subject_id,
        )
    return {"items": [dto(row) for row in rows]}


@router.post("")
async def assign(
    body: Assign,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
):
    require_scope(actor, "identity.private-seller.assign")
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    async with unit_of_work(
        request.app.state.pool, lock_key="l02.review-op:" + str(actor.actor.subject_id)
    ) as tx:
        case = await application(tx, body.application_id)
        await lock_accounts(
            tx, actor.actor.subject_id, case["subject_id"], body.reviewer_id
        )
        await require_current(
            tx, request, "identity.private-seller.assign", actor.actor.subject_id
        )
        old = await previous(tx, actor.actor.subject_id, key, fingerprint)
        if old:
            return old
        case = await application(tx, body.application_id, lock=True)
        await qualified_reviewer(tx, body.reviewer_id, case["subject_id"])
        if await tx.fetchval(
            "SELECT id FROM l02_private_reviews WHERE application_id=$1",
            body.application_id,
        ):
            raise PublicError("review_exists", "Use the existing review.", status=409)
        row = await tx.fetchrow(
            """INSERT INTO l02_private_reviews(id,application_id,applicant_id,reviewer_id,application_revision)
            VALUES($1,$2,$3,$4,$5) RETURNING *""",
            uuid4(),
            body.application_id,
            case["subject_id"],
            body.reviewer_id,
            case["revision"],
        )
        await assignment(tx, body.application_id, body.reviewer_id)
        result = await record(
            tx,
            request,
            actor.actor.subject_id,
            key,
            fingerprint,
            row,
            body.reason,
            "identity.private-review-assigned.v1",
        )
    return result


@router.get("/{review_id}")
async def detail(
    review_id: UUID,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    before_revision: int | None = Query(default=None, ge=1, le=2147483647),
):
    async with unit_of_work(request.app.state.pool) as tx:
        await live_actor(tx, request, lock=True)
        row = await tx.fetchrow(
            "SELECT * FROM l02_private_reviews WHERE id=$1", review_id
        )
        if not row or actor.actor.subject_id not in {
            row["applicant_id"],
            row["reviewer_id"],
        }:
            raise AccessDenied(
                "Only the applicant or currently assigned reviewer may read the review. / "
                "لا يمكن قراءة المراجعة إلا لمقدم الطلب أو المراجع المعيّن حاليًا."
            )
        if actor.actor.subject_id == row["reviewer_id"]:
            await require_current(
                tx, request, "identity.private-seller.review", actor.actor.subject_id
            )
        history = await tx.fetch(
            """SELECT revision,state,reason,created_at FROM l02_private_review_history
            WHERE review_id=$1 AND ($2::integer IS NULL OR revision<$2)
            ORDER BY revision DESC LIMIT 101""",
            review_id,
            before_revision,
        )
        case = await application(tx, row["application_id"])
    return {
        **dto(row),
        "application_revision": case["revision"],
        "history": [dict(item) for item in reversed(history[:100])],
        "history_before_revision": history[99]["revision"]
        if len(history) > 100
        else None,
        "physical_watch_authentication": False,
        "business_privileges": False,
    }


@router.post("/{review_id}/verdict")
async def verdict(
    review_id: UUID,
    body: Verdict,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
):
    require_scope(actor, "identity.private-seller.review")
    fingerprint = hashlib.sha256(
        (str(review_id) + body.model_dump_json()).encode()
    ).hexdigest()
    async with unit_of_work(
        request.app.state.pool, lock_key="l02.review-op:" + str(actor.actor.subject_id)
    ) as tx:
        target = await tx.fetchrow(
            "SELECT applicant_id FROM l02_private_reviews WHERE id=$1", review_id
        )
        if not target:
            raise AccessDenied("Assigned independent reviewer required")
        await lock_accounts(tx, actor.actor.subject_id, target["applicant_id"])
        await require_current(
            tx, request, "identity.private-seller.review", actor.actor.subject_id
        )
        row = await tx.fetchrow(
            "SELECT * FROM l02_private_reviews WHERE id=$1 FOR UPDATE", review_id
        )
        if (
            row["reviewer_id"] != actor.actor.subject_id
            or row["applicant_id"] == actor.actor.subject_id
        ):
            raise AccessDenied("Assigned independent reviewer required")
        old = await previous(tx, actor.actor.subject_id, key, fingerprint)
        if old:
            return old
        if row["revision"] != body.revision:
            raise PublicError(
                "stale_revision", "Reload the current review.", status=409
            )
        case = await application(tx, row["application_id"], lock=True)
        if case["subject_id"] != row["applicant_id"]:
            raise AccessDenied("Private individual binding changed")
        if case["revision"] != body.application_revision:
            raise PublicError(
                "stale_application",
                "The application changed; inspect it again.",
                status=409,
            )
        if body.state == "approved" and not case["complete"]:
            raise PublicError(
                "incomplete_application",
                "Complete evidence is required before approval.",
                status=409,
            )
        subject = row["applicant_id"]
        if (
            body.state == "approved"
            and await tx.fetchval(
                "SELECT status FROM identity_accounts WHERE id=$1", subject
            )
            != "active"
        ):
            raise PublicError(
                "applicant_unavailable",
                "An active applicant is required before approval.",
                status=409,
            )
        grant = await tx.fetchval(
            "SELECT id FROM identity_access_grants WHERE subject_id=$1 AND organization_id IS NULL AND role='private_seller' AND revoked_at IS NULL LIMIT 1",
            subject,
        )
        if body.state == "approved" and not grant:
            await tx.execute(
                "INSERT INTO identity_access_grants(id,subject_id,role,permissions) VALUES($1,$2,'private_seller',ARRAY['identity.listings.publish'])",
                uuid4(),
                subject,
            )
        elif body.state != "approved":
            await tx.execute(
                "UPDATE identity_access_grants SET revoked_at=coalesce(revoked_at,now()) WHERE subject_id=$1 AND organization_id IS NULL AND role='private_seller'",
                subject,
            )
            if grant or body.state in {"suspended", "rejected"}:
                await tx.execute(
                    "UPDATE identity_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE subject_id=$1",
                    subject,
                )
        await tx.execute(
            "UPDATE identity_accounts SET access_revision=access_revision+1 WHERE id=$1",
            subject,
        )
        case = await tx.fetchrow(
            """UPDATE identity_private_applications SET status=$2,reason=$3,revision=revision+1,updated_at=now()
            WHERE id=$1 RETURNING *""",
            row["application_id"],
            body.state,
            body.reason,
        )
        row = await tx.fetchrow(
            """UPDATE l02_private_reviews SET state=$2,application_revision=$3,revision=revision+1,updated_at=now()
            WHERE id=$1 RETURNING *""",
            review_id,
            body.state,
            case["revision"],
        )
        result = await record(
            tx,
            request,
            actor.actor.subject_id,
            key,
            fingerprint,
            row,
            body.reason,
            "identity.private-seller-reviewed.v1",
        )
    return result


@router.post("/{review_id}/reassign")
async def reassign(
    review_id: UUID,
    body: Reassign,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
):
    require_scope(actor, "identity.private-seller.assign")
    fingerprint = hashlib.sha256(
        (str(review_id) + body.model_dump_json()).encode()
    ).hexdigest()
    async with unit_of_work(
        request.app.state.pool, lock_key="l02.review-op:" + str(actor.actor.subject_id)
    ) as tx:
        target = await tx.fetchrow(
            "SELECT applicant_id,reviewer_id FROM l02_private_reviews WHERE id=$1",
            review_id,
        )
        if not target:
            raise PublicError("not_found", "Review not found.", status=404)
        await lock_accounts(
            tx,
            actor.actor.subject_id,
            target["applicant_id"],
            target["reviewer_id"],
            body.reviewer_id,
        )
        await require_current(
            tx, request, "identity.private-seller.assign", actor.actor.subject_id
        )
        old = await previous(tx, actor.actor.subject_id, key, fingerprint)
        if old:
            return old
        row = await tx.fetchrow(
            "SELECT * FROM l02_private_reviews WHERE id=$1 FOR UPDATE", review_id
        )
        if row["revision"] != body.revision:
            raise PublicError(
                "stale_revision", "Reload the current review.", status=409
            )
        await qualified_reviewer(tx, body.reviewer_id, row["applicant_id"])
        row = await tx.fetchrow(
            "UPDATE l02_private_reviews SET reviewer_id=$2,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",
            review_id,
            body.reviewer_id,
        )
        await assignment(tx, row["application_id"], body.reviewer_id)
        result = await record(
            tx,
            request,
            actor.actor.subject_id,
            key,
            fingerprint,
            row,
            body.reason,
            "identity.private-review-assigned.v1",
        )
    return result


legacy_router = router
router = APIRouter()
router.include_router(legacy_router)


async def review_page(request, actor, page, page_size, *, own):
    field = "applicant_id" if own else "reviewer_id"
    async with unit_of_work(request.app.state.pool) as tx:
        await tx.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await live_actor(tx, request, lock=True)
        if not own:
            await require_current(tx, request, "identity.private-seller.review", actor.actor.subject_id)
        total = await tx.fetchval(
            f"SELECT count(*) FROM l02_private_reviews WHERE {field}=$1", actor.actor.subject_id)
        rows = await tx.fetch(
            f"SELECT * FROM l02_private_reviews WHERE {field}=$1 ORDER BY updated_at DESC,id LIMIT $2 OFFSET $3",
            actor.actor.subject_id, page_size, (page - 1) * page_size)
    return {"items": [dto(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/v2/private-reviews")
async def queue_v2(request: Request, actor: CurrentPrincipal = Depends(principal),
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=25)):
    return await review_page(request, actor, page, page_size, own=False)


@router.get("/v2/private-reviews/mine")
async def mine_v2(request: Request, actor: CurrentPrincipal = Depends(principal),
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=25)):
    return await review_page(request, actor, page, page_size, own=True)


@router.get("/v2/private-reviews/{review_id}")
async def detail_v2(
    review_id: UUID,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    before_revision: int | None = Query(default=None, ge=1, le=2147483647),
):
    async with unit_of_work(request.app.state.pool) as tx:
        await tx.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await live_actor(tx, request, lock=True)
        row = await tx.fetchrow(
            "SELECT * FROM l02_private_reviews WHERE id=$1", review_id
        )
        if not row or actor.actor.subject_id not in {
            row["applicant_id"],
            row["reviewer_id"],
        }:
            raise AccessDenied(
                "Only the applicant or currently assigned reviewer may read the review. / "
                "لا يمكن قراءة المراجعة إلا لمقدم الطلب أو المراجع المعيّن حاليًا."
            )
        if actor.actor.subject_id == row["reviewer_id"]:
            await require_current(
                tx, request, "identity.private-seller.review", actor.actor.subject_id
            )
        history = await tx.fetch(
            """SELECT revision,state,reason,created_at FROM l02_private_review_history
            WHERE review_id=$1 AND ($2::integer IS NULL OR revision<$2)
            ORDER BY revision DESC LIMIT 26""",
            review_id,
            before_revision,
        )
        total = await tx.fetchval("SELECT count(*) FROM l02_private_review_history WHERE review_id=$1", review_id)
        case = await application(tx, row["application_id"])
    return {
        **dto(row),
        "application_revision": case["revision"],
        "history_total": total,
        "history": [dict(item) for item in reversed(history[:25])],
        "history_before_revision": history[24]["revision"]
        if len(history) > 25
        else None,
        "physical_watch_authentication": False,
        "business_privileges": False,
    }
