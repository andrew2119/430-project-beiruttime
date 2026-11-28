"""All-five source validation, immutable submission and revision-safe corrections."""

import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Request, Query, Response
from bt_contracts.catalog.request_drafts.v2 import SubmitRequest, Correction
from bt_contracts.catalog.brand_decisions.v1 import RequestEvent
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from service_app.catalog_dependencies import principal
from service_app.configuration import configuration, selections, digest
from service_app.customization import (
    current,
    view,
    readable,
    service,
    active_brand,
    decode,
)

router = APIRouter()


def key(request):
    value = request.headers.get("Idempotency-Key", "")
    if (
        not value
        or len(value) > 100
        or any(not (c.isascii() and (c.isalnum() or c in "_-:.")) for c in value)
    ):
        raise PublicError(
            "idempotency_required", "Supply a stable operation key.", status=422
        )
    return value


async def prior(tx, actor_id, operation_key, fingerprint):
    op = await tx.fetchrow(
        "SELECT * FROM catalog_customization_operations WHERE actor_id=$1 AND operation_key=$2",
        actor_id,
        operation_key,
    )
    if op:
        if op["digest"] != fingerprint:
            raise PublicError(
                "idempotency_conflict",
                "This key belongs to another request.",
                status=409,
            )
        return decode(op["result"])


async def record(tx, request, row, rev, actor_id, operation_key, fingerprint, kind):
    result = {
        "id": str(uuid4()),
        "status": "succeeded",
        "resource_id": str(row["id"]),
        "request": view(row, rev),
    }
    await tx.execute(
        "INSERT INTO catalog_customization_operations(id,request_id,actor_id,operation_key,digest,result) VALUES($1,$2,$3,$4,$5,$6::jsonb)",
        UUID(result["id"]),
        row["id"],
        actor_id,
        operation_key,
        fingerprint,
        json.dumps(result),
    )
    await enqueue(
        tx,
        EventEnvelope(
            type=f"catalog.customization.{kind}.v2",
            source="catalog",
            subject=str(row["id"]),
            request_id=request.state.request_id,
            data=RequestEvent(
                request_id=row["id"],
                request_revision=row["revision"],
                brand_id=row["brand_id"],
            ).model_dump(mode="json"),
        ),
        ["service-operations-brand-assessment"],
    )
    return result


@router.post("/v1/request-drafts/{draft_id}/submit")
@router.post("/v2/request-drafts/{draft_id}/submit")
async def submit(draft_id: UUID, body: SubmitRequest, request: Request):
    person = await principal(request)
    if "buyer" not in person.roles or person.actor.organization_id:
        raise AccessDenied("Personal buyer scope required")
    owner, operation_key = person.actor.subject_id, key(request)
    fingerprint = digest({"draft_id": str(draft_id), **body.model_dump(mode="json")})
    async with request.app.state.pool.acquire() as tx:
        draft = await tx.fetchrow(
            "SELECT * FROM l08_request_drafts WHERE id=$1 AND owner_id=$2",
            draft_id,
            owner,
        )
        previous = await prior(tx, owner, operation_key, fingerprint)
    if draft is None:
        raise PublicError("not_found", "Draft not found.", status=404)
    if previous:
        return previous
    content = decode(draft["content"])
    if content.get("kind") != "customization" or not content.get("brand_id"):
        raise PublicError(
            "draft_incomplete",
            "Choose a customization brand.",
            status=422,
            details={"fields": {"brand": "missing"}},
        )
    brand_id = UUID(content["brand_id"])
    await active_brand(request, brand_id)
    if (
        content.get("watch_context") not in ("owned_watch", "seller_base")
        or not content.get("watch_reference", "").strip()
    ):
        raise PublicError(
            "draft_incomplete",
            "Choose the watch context.",
            status=422,
            details={"fields": {"watch_context": "missing"}},
        )
    # A seller reference expresses intent; only the later purchase owns allocation.
    async with unit_of_work(
        request.app.state.pool, lock_key=f"l15-request-op:{owner}:{operation_key}"
    ) as tx:
        previous = await prior(tx, owner, operation_key, fingerprint)
        if previous:
            return previous
        draft = await tx.fetchrow(
            "SELECT * FROM l08_request_drafts WHERE id=$1 AND owner_id=$2 FOR UPDATE",
            draft_id,
            owner,
        )
        if draft is None:
            raise PublicError("not_found", "Draft not found.", status=404)
        if draft["submitted_request_id"]:
            raise PublicError(
                "already_submitted",
                "Reopen the submitted request instead.",
                status=409,
                details={"request_id": str(draft["submitted_request_id"])},
            )
        if (
            draft["revision"] != body.draft_revision
            or decode(draft["content"]) != content
        ):
            raise PublicError("stale_revision", "Reload the saved draft.", status=409)
        if (
            content.get("configuration_id") != str(body.configuration_id)
            or content.get("configuration_revision") != body.configuration_revision
        ):
            raise PublicError(
                "configuration_binding",
                "Save this current configuration to the draft first.",
                status=409,
            )
        validated = await configuration(
            tx,
            owner,
            body.configuration_id,
            body.configuration_revision,
            body.movement_selection_id,
            body.movement_revision,
        )
        if validated["snapshot"]["brand_id"] != str(brand_id):
            raise PublicError(
                "configuration_binding",
                "Choose this brand's configuration.",
                status=409,
            )
        if validated["digest"] != body.expected_digest:
            raise PublicError(
                "stale_configuration",
                "Validate the current configuration before submission.",
                status=409,
            )
        if validated["status"] in ("incompatible", "parts_unavailable"):
            raise PublicError(
                "configuration_incomplete",
                "Review the current configuration.",
                status=422,
                details={"fields": validated["fields"], "status": validated["status"]},
            )
        row = await tx.fetchrow(
            "INSERT INTO catalog_customization_requests(id,draft_id,buyer_id,brand_id) VALUES($1,$2,$3,$4) RETURNING *",
            uuid4(),
            draft_id,
            owner,
            brand_id,
        )
        # A watch context is a request declaration, never proof of custody or authority.
        saved_content = {
            name: content[name]
            for name in ("watch_context", "watch_reference", "scope_intent", "notes")
        }
        rev = await tx.fetchrow(
            "INSERT INTO catalog_customization_revisions(request_id,revision,configuration_digest,configuration,content,actor_id,reason) VALUES($1,1,$2,$3::jsonb,$4::jsonb,$5,$6) RETURNING *",
            row["id"],
            validated["digest"],
            json.dumps(validated["snapshot"]),
            json.dumps(saved_content),
            owner,
            "Buyer submitted current configuration",
        )
        await tx.execute(
            "UPDATE l08_request_drafts SET submitted_request_id=$2 WHERE id=$1",
            draft_id,
            row["id"],
        )
        return await record(
            tx, request, row, rev, owner, operation_key, fingerprint, "submitted"
        )


@router.get("/v1/customization-requests")
@router.get("/v2/customization-requests")
async def requests(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    draft_id: UUID | None = None,
    before: UUID | None = None,
):
    person = await principal(request)
    org = person.actor.organization_id
    if org:
        require_scope(person, "business.jobs.write", org)
        await active_brand(request, org)
    elif "buyer" not in person.roles:
        raise AccessDenied("Buyer scope required")
    async with request.app.state.pool.acquire() as tx:
        if before is not None and not await tx.fetchval(
            "SELECT 1 FROM catalog_customization_requests WHERE id=$3 AND (($1::uuid IS NOT NULL AND brand_id=$1) OR ($1::uuid IS NULL AND buyer_id=$2)) AND ($4::uuid IS NULL OR draft_id=$4)",
            org,
            person.actor.subject_id,
            before,
            draft_id,
        ):
            raise PublicError(
                "invalid_cursor", "Reload the first requests page.", status=422
            )
        rows = await tx.fetch(
            "SELECT id FROM catalog_customization_requests WHERE (($1::uuid IS NOT NULL AND brand_id=$1) OR ($1::uuid IS NULL AND buyer_id=$2)) AND ($4::uuid IS NULL OR draft_id=$4) AND ($5::uuid IS NULL OR (created_at,id)<(SELECT created_at,id FROM catalog_customization_requests WHERE id=$5)) ORDER BY created_at DESC,id DESC LIMIT $3",
            org,
            person.actor.subject_id,
            limit + 1,
            draft_id,
            before,
        )
        items = []
        for item in rows[:limit]:
            row, rev = await current(tx, item["id"])
            items.append(view(row, rev))
    return {
        "items": items,
        "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
    }


@router.get("/v1/customization-requests/{request_id}")
@router.get("/v2/customization-requests/{request_id}")
async def get(request_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row, rev = await current(tx, request_id)
    await readable(request, row)
    return view(row, rev)


@router.get("/internal/v2/customization-requests/{request_id}")
async def internal(
    request_id: UUID,
    request: Request,
    expected_revision: int | None = Query(None, ge=1),
):
    service(request, {"service-operations", "pricing", "eligibility", "orders"})
    async with request.app.state.pool.acquire() as tx:
        row, rev = await current(tx, request_id)
    if expected_revision is not None and row["revision"] != expected_revision:
        raise PublicError("stale_revision", "The request revision changed.", status=409)
    return view(row, rev, internal=True)


@router.get("/v1/customization-operations/{operation_id}")
@router.get("/v2/customization-operations/{operation_id}")
async def operation(operation_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        op = await tx.fetchrow(
            "SELECT * FROM catalog_customization_operations WHERE id=$1", operation_id
        )
        if not op:
            raise PublicError("not_found", "Operation not found.", status=404)
        row, _ = await current(tx, op["request_id"])
    await readable(request, row)
    return decode(op["result"])


@router.post("/v1/customization-requests/{request_id}/corrections")
@router.post("/v2/customization-requests/{request_id}/corrections")
async def correct(request_id: UUID, body: Correction, request: Request):
    # Only Service Operations may originate a technical correction after fencing
    # its current qualified claim/assignment. A browser role is not that authority.
    # Fresh human/org permission is still required alongside signed provenance.
    service(request, {"service-operations"}, header="X-Service-Authorization")
    person = await principal(request)
    operation_key = key(request)
    fingerprint = digest(
        {"request_id": str(request_id), **body.model_dump(mode="json")}
    )
    async with request.app.state.pool.acquire() as tx:
        row, _ = await current(tx, request_id)
    require_scope(person, "business.jobs.write", row["brand_id"])
    await active_brand(request, row["brand_id"])
    if person.actor.subject_id == row["buyer_id"]:
        raise AccessDenied("Buyer cannot correct as the brand")
    async with unit_of_work(
        request.app.state.pool,
        lock_key=f"l15-request-op:{person.actor.subject_id}:{operation_key}",
    ) as tx:
        await tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            f"l15-request:{request_id}",
        )
        previous = await prior(tx, person.actor.subject_id, operation_key, fingerprint)
        if previous:
            return previous
        row, rev = await current(tx, request_id, lock=True)
        if row["revision"] != body.expected_revision:
            raise PublicError(
                "stale_revision", "Reload the current request.", status=409
            )
        # Decision table is installed by the module that owns the saga. If absent,
        # no decision can exist; this avoids a migration ordering/schema dependency.
        if await tx.fetchval("SELECT to_regclass('catalog_brand_decisions')"):
            if await tx.fetchval(
                "SELECT 1 FROM catalog_brand_decisions WHERE request_id=$1 AND status IN ('pending','approved')",
                request_id,
            ):
                raise PublicError(
                    "decision_pending",
                    "Reconcile or invalidate the current decision before correcting.",
                    status=409,
                )
        old = decode(rev["configuration"])
        await tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            f"l10-brand:{row['brand_id']}",
        )
        validated = await selections(
            tx,
            brand_id=row["brand_id"],
            base_model=old["base_model"],
            caliber=old["caliber"],
            chosen={
                kind: selection.model_dump()
                for kind, selection in body.selections.items()
            },
            mounting=old["movement_mounting"],
            reference_ids=old["reference_ids"],
        )
        if validated["status"] in ("incompatible", "parts_unavailable"):
            raise PublicError(
                "configuration_incomplete",
                "Correction requires compatible current parts.",
                status=422,
                details={"fields": validated["fields"]},
            )
        row = await tx.fetchrow(
            "UPDATE catalog_customization_requests SET revision=revision+1 WHERE id=$1 RETURNING *",
            request_id,
        )
        rev = await tx.fetchrow(
            "INSERT INTO catalog_customization_revisions(request_id,revision,configuration_digest,configuration,content,actor_id,reason) VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7) RETURNING *",
            request_id,
            row["revision"],
            validated["digest"],
            json.dumps(validated["snapshot"]),
            json.dumps(decode(rev["content"])),
            person.actor.subject_id,
            body.reason,
        )
        return await record(
            tx,
            request,
            row,
            rev,
            person.actor.subject_id,
            operation_key,
            fingerprint,
            "corrected",
        )


@router.get("/v1/customization-requests/{request_id}/revisions")
@router.get("/v2/customization-requests/{request_id}/revisions")
async def history(
    request_id: UUID,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    before_revision: int | None = Query(None, ge=1, le=2147483647),
):
    async with request.app.state.pool.acquire() as tx:
        row, _ = await current(tx, request_id)
    await readable(request, row)
    revisions = await request.app.state.pool.fetch(
        "SELECT * FROM catalog_customization_revisions WHERE request_id=$1 AND revision<=$4 AND ($2::integer IS NULL OR revision<$2) ORDER BY revision DESC LIMIT $3",
        request_id,
        before_revision,
        limit + 1,
        row["revision"],
    )
    return {
        "current_revision": row["revision"],
        "total": row["revision"],
        "next_cursor": revisions[limit - 1]["revision"] if len(revisions) > limit else None,
        "items": [
            {
                **view({**dict(row), "revision": rev["revision"]}, rev),
                "actor_id": str(rev["actor_id"]),
                "reason": rev["reason"],
            }
            for rev in revisions[:limit]
        ],
    }


@router.get("/v1/customization-requests/{request_id}/references/{reference_id}")
@router.get("/v2/customization-requests/{request_id}/references/{reference_id}")
async def reference(request_id: UUID, reference_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row, rev = await current(tx, request_id)
    await readable(request, row)
    if str(reference_id) not in decode(rev["configuration"])["reference_ids"]:
        raise PublicError("not_found", "Reference not found.", status=404)
    content = await request.app.state.pool.fetchval(
        "SELECT content FROM l10_references WHERE id=$1 AND owner_id=$2",
        reference_id,
        row["buyer_id"],
    )
    if content is None:
        raise PublicError("not_found", "Reference not found.", status=404)
    return Response(
        bytes(content),
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
