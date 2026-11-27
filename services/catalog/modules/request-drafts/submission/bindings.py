"""Authenticated source receipts, separate from immutable submitted content."""

import json
from uuid import UUID
from fastapi import APIRouter, Request
from bt_contracts.catalog.request_drafts.bindings import WatchBinding, AssignmentBinding, CurrentBinding
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from service_app.configuration import digest
from service_app.customization import current, readable, service, decode

router = APIRouter()


def projection(row):
    return {
        "request_id": str(row["id"]),
        "request_revision": row["revision"],
        "binding_revision": row["binding_revision"],
        **{name: str(row[name]) if row[name] else None for name in (
            "watch_id", "recovery_operator_id", "assessor_id", "approver_id", "quality_reviewer_id"
        )},
    }


async def retain(request_id, body, request, kind):
    producer = service(request, {"orders"} if kind == "watch" else {"service-operations"})
    fingerprint = digest(body.model_dump(mode="json"))
    async with unit_of_work(request.app.state.pool, lock_key=f"l15-request:{request_id}") as tx:
        row, _ = await current(tx, request_id, lock=True)
        if body.buyer_id != row["buyer_id"] or body.brand_id != row["brand_id"]:
            raise AccessDenied("Source scope differs")
        previous = await tx.fetchrow(
            "SELECT * FROM catalog_request_binding_history WHERE producer=$1 AND operation_id=$2",
            producer, body.operation_id,
        )
        if previous:
            if previous["request_id"] != request_id or previous["digest"] != fingerprint:
                raise PublicError("idempotency_conflict", "Source operation differs.", status=409)
            return decode(previous["result"])
        if row["revision"] != body.request_revision or row["binding_revision"] != body.expected_binding_revision:
            raise PublicError("stale_revision", "Reload current request bindings.", status=409)
        source_revision = await tx.fetchval(
            "SELECT max(source_revision) FROM catalog_request_binding_history WHERE request_id=$1 AND producer=$2",
            request_id, producer,
        )
        if source_revision is not None and body.source_revision <= source_revision:
            raise PublicError("stale_revision", "Source revision changed.", status=409)
        if await tx.fetchval("SELECT to_regclass('catalog_brand_decisions')") and await tx.fetchval(
            "SELECT 1 FROM catalog_brand_decisions WHERE request_id=$1 AND status IN ('pending','approved')", request_id
        ):
            raise PublicError("decision_pending", "Reconcile the current decision first.", status=409)
        if kind == "assignment":
            if row["watch_id"] != body.watch_id:
                raise PublicError("watch_binding", "Assignment must match the current watch.", status=409)
            if (len({body.assessor_id, body.approver_id, body.quality_reviewer_id}) != 3
                    or body.buyer_id in {body.assessor_id, body.approver_id, body.quality_reviewer_id,
                                         body.recovery_operator_id}):
                raise AccessDenied("Independent current assignments required")
            row = await tx.fetchrow(
                "UPDATE catalog_customization_requests SET assessor_id=$2,approver_id=$3,quality_reviewer_id=$4,"
                "recovery_operator_id=$5,binding_revision=binding_revision+1 WHERE id=$1 RETURNING *",
                request_id, body.assessor_id, body.approver_id, body.quality_reviewer_id, body.recovery_operator_id,
            )
        else:
            row = await tx.fetchrow(
                "UPDATE catalog_customization_requests SET watch_id=$2,assessor_id=NULL,approver_id=NULL,"
                "quality_reviewer_id=NULL,recovery_operator_id=NULL,binding_revision=binding_revision+1 "
                "WHERE id=$1 RETURNING *", request_id, body.watch_id,
            )
        result = projection(row)
        await tx.execute(
            "INSERT INTO catalog_request_binding_history(request_id,binding_revision,producer,operation_id,"
            "source_revision,digest,command,result) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb)",
            request_id, row["binding_revision"], producer, body.operation_id, body.source_revision,
            fingerprint, body.model_dump_json(), json.dumps(result),
        )
        return result


@router.post("/internal/v2/customization-requests/{request_id}/owned-watch", response_model=CurrentBinding)
async def owned_watch(request_id: UUID, body: WatchBinding, request: Request):
    return await retain(request_id, body, request, "watch")


@router.post("/internal/v2/customization-requests/{request_id}/assignment", response_model=CurrentBinding)
async def assignment(request_id: UUID, body: AssignmentBinding, request: Request):
    return await retain(request_id, body, request, "assignment")


@router.get("/internal/v2/customization-requests/{request_id}/bindings", response_model=CurrentBinding)
async def internal_binding(request_id: UUID, request: Request):
    service(request, {"orders", "service-operations", "eligibility", "pricing"})
    async with request.app.state.pool.acquire() as tx:
        row, _ = await current(tx, request_id)
    return projection(row)


@router.get("/v2/customization-requests/{request_id}/bindings", response_model=CurrentBinding)
async def binding(request_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row, _ = await current(tx, request_id)
    await readable(request, row)
    return projection(row)


@router.get("/v2/customization-requests/{request_id}/bindings/revisions")
async def history(request_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row, _ = await current(tx, request_id)
        await readable(request, row)
        rows = await tx.fetch(
            "SELECT result FROM catalog_request_binding_history WHERE request_id=$1 "
            "ORDER BY binding_revision DESC LIMIT 100", request_id,
        )
    return {"binding_revision": row["binding_revision"], "items": [decode(item["result"]) for item in rows]}
