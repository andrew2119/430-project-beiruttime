import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Request
from bt_contracts.catalog.request_drafts.v2 import Decision
from bt_contracts.catalog.brand_decisions.v1 import DecisionEvent
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from service_app.catalog_dependencies import principal
from service_app.configuration import digest
from service_app.customization import current, readable, active_brand, service, decode
from . import authority

router = APIRouter()


def dto(op):
    return {
        "id": str(op["id"]),
        "request_id": str(op["request_id"]),
        "request_revision": op["request_revision"],
        "brand_id": str(op["brand_id"]),
        "actor_id": str(op["actor_id"]),
        "status": op["status"],
        "reason": decode(op["intent"])["reason"],
        "bindings": decode(op["bindings"]) if op["bindings"] else None,
        "code": op["code"],
        "confirmed_at": op["confirmed_at"].isoformat() if op["confirmed_at"] else None,
        "execution_authority": False,
    }


async def approver(request, row):
    person = await principal(request)
    require_scope(person, "business.jobs.write", row["brand_id"])
    await active_brand(request, row["brand_id"])
    if person.actor.subject_id == row["buyer_id"]:
        raise AccessDenied("Buyer cannot approve the same case")
    return person


async def resume(request, operation_id):
    async with request.app.state.pool.acquire() as tx:
        op = await tx.fetchrow(
            "SELECT * FROM catalog_brand_decisions WHERE id=$1", operation_id
        )
        if not op:
            raise PublicError("not_found", "Decision operation not found.", status=404)
        row, _ = await current(tx, op["request_id"])
    person = await approver(request, row)
    if person.actor.subject_id != op["actor_id"]:
        raise AccessDenied("Only the current decision actor may reconcile this intent")
    if op["status"] != "pending":
        return dto(op)
    if row["revision"] != op["request_revision"]:
        raise PublicError("stale_scope", "The request revision changed.", status=409)
    intent = decode(op["intent"])
    try:
        # This intent was durably retained before any prerequisite/approval HTTP.
        bindings = decode(op["bindings"]) if op["bindings"] else None
        if bindings is None:
            values = await authority.current(request, row, intent)
            bindings = authority.bind(values, row, intent, person.actor.subject_id)
            async with unit_of_work(
                request.app.state.pool, lock_key=f"l15-request:{row['id']}"
            ) as tx:
                await tx.execute(
                    "UPDATE catalog_brand_decisions SET bindings=$2::jsonb WHERE id=$1 AND status='pending' AND bindings IS NULL",
                    operation_id,
                    json.dumps(bindings),
                )
        # A consumed grant may no longer appear in the current-grants list. Resume
        # the exact retained authority operation instead of treating that as denial.
        await authority.consume(request, operation_id, bindings)
    except (PublicError, AccessDenied) as error:
        if isinstance(error, PublicError) and error.status >= 500:
            raise  # unknown outcome remains durable pending
        code = error.code if isinstance(error, PublicError) else "approval_forbidden"
        async with unit_of_work(
            request.app.state.pool, lock_key=f"l15-request:{row['id']}"
        ) as tx:
            op = await tx.fetchrow(
                "UPDATE catalog_brand_decisions SET status='denied',code=$2 WHERE id=$1 AND status='pending' RETURNING *",
                operation_id,
                code,
            )
            if op is None:
                op = await tx.fetchrow(
                    "SELECT * FROM catalog_brand_decisions WHERE id=$1", operation_id
                )
        return dto(op)
    person = await approver(request, row)
    async with unit_of_work(
        request.app.state.pool, lock_key=f"l15-request:{row['id']}"
    ) as tx:
        row, _ = await current(tx, row["id"], lock=True)
        op = await tx.fetchrow(
            "SELECT * FROM catalog_brand_decisions WHERE id=$1 FOR UPDATE", operation_id
        )
        if op["status"] != "pending":
            return dto(op)
        if (
            row["revision"] != op["request_revision"]
            or person.actor.subject_id != op["actor_id"]
        ):
            raise PublicError(
                "stale_scope", "The current actor or request changed.", status=409
            )
        state = "approved" if intent["decision"] == "approve" else "rejected"
        op = await tx.fetchrow(
            "UPDATE catalog_brand_decisions SET status=$2,confirmed_at=clock_timestamp() WHERE id=$1 RETURNING *",
            operation_id,
            state,
        )
        await enqueue(
            tx,
            EventEnvelope(
                type="catalog.brand-decision.confirmed.v1",
                source="catalog",
                subject=str(row["id"]),
                request_id=request.state.request_id,
                data=DecisionEvent(
                    request_id=row["id"],
                    request_revision=row["revision"],
                    brand_id=row["brand_id"],
                    decision_id=operation_id,
                    status=state,
                ).model_dump(mode="json"),
            ),
            ["orders-brand-jobs"],
        )
        return dto(op)


@router.get("/v1/customization-requests/{request_id}/decision-readiness")
@router.get("/v2/customization-requests/{request_id}/decision-readiness")
async def readiness(request_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row, _ = await current(tx, request_id)
    person = await approver(request, row)
    try:
        values = await authority.current(request, row)
        intent = {
            kind + suffix: value["id" if suffix == "_id" else "revision"]
            for kind, value in values.items()
            for suffix in ("_id", "_revision")
        }
        bindings = authority.bind(values, row, intent, person.actor.subject_id)
    except PublicError as error:
        if error.status < 500:
            raise
        # Optional upstream facts must not open the BFF's healthy Catalog
        # circuit and poison unrelated listing/request reads. This is not an
        # approval; the command path still fails closed with durable pending.
        return {'status':'unavailable','code':'approval_unavailable','execution_authority':False}
    return {'status':'available','bindings':bindings,'execution_authority':False}


@router.post("/v1/customization-requests/{request_id}/decisions")
@router.post("/v2/customization-requests/{request_id}/decisions")
async def decide(request_id: UUID, body: Decision, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row, _ = await current(tx, request_id)
    person = await approver(request, row)
    operation_key = request.headers.get("Idempotency-Key", "")
    if (
        not operation_key
        or len(operation_key) > 100
        or not all(c.isascii() and (c.isalnum() or c in "_-:.") for c in operation_key)
    ):
        raise PublicError(
            "idempotency_required", "Supply a stable decision key.", status=422
        )
    intent = body.model_dump(mode="json")
    fingerprint = digest({"request_id": str(request_id), **intent})
    async with unit_of_work(
        request.app.state.pool,
        lock_key=f"l15-decision-op:{person.actor.subject_id}:{operation_key}",
    ) as tx:
        row, _ = await current(tx, request_id, lock=True)
        op = await tx.fetchrow(
            "SELECT * FROM catalog_brand_decisions WHERE actor_id=$1 AND operation_key=$2",
            person.actor.subject_id,
            operation_key,
        )
        if op:
            if op["digest"] != fingerprint:
                raise PublicError(
                    "idempotency_conflict",
                    "This decision key belongs to a different scope.",
                    status=409,
                )
        else:
            if row["revision"] != body.expected_revision:
                raise PublicError(
                    "stale_revision", "Reload the current request revision.", status=409
                )
            if await tx.fetchval(
                "SELECT 1 FROM catalog_brand_decisions WHERE request_id=$1 AND request_revision=$2 AND status IN ('pending','approved','rejected')",
                request_id,
                row["revision"],
            ):
                raise PublicError(
                    "decision_exists", "Reconcile the existing decision.", status=409
                )
            op = await tx.fetchrow(
                "INSERT INTO catalog_brand_decisions(id,request_id,request_revision,actor_id,brand_id,operation_key,digest,intent) VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb) RETURNING *",
                uuid4(),
                request_id,
                row["revision"],
                person.actor.subject_id,
                row["brand_id"],
                operation_key,
                fingerprint,
                json.dumps(intent),
            )
    return await resume(request, op["id"])


@router.post("/v1/brand-decision-operations/{operation_id}/resume")
@router.post("/v2/brand-decision-operations/{operation_id}/resume")
async def reconcile(operation_id: UUID, request: Request):
    return await resume(request, operation_id)


@router.get("/v1/brand-decision-operations/{operation_id}")
@router.get("/v2/brand-decision-operations/{operation_id}")
async def operation(operation_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        op = await tx.fetchrow(
            "SELECT * FROM catalog_brand_decisions WHERE id=$1", operation_id
        )
        if not op:
            raise PublicError("not_found", "Decision operation not found.", status=404)
        row, _ = await current(tx, op["request_id"])
    await readable(request, row)
    return dto(op)


async def decision(request, request_id, internal=False):
    async with request.app.state.pool.acquire() as tx:
        row, _ = await current(tx, request_id)
        op = await tx.fetchrow(
            "SELECT * FROM catalog_brand_decisions WHERE request_id=$1 AND request_revision=$2 ORDER BY created_at DESC LIMIT 1",
            request_id,
            row["revision"],
        )
    if not internal:
        await readable(request, row)
    return (
        dto(op)
        if op
        else {
            "status": "not_decided",
            "request_id": str(request_id),
            "request_revision": row["revision"],
            "execution_authority": False,
        }
    )


@router.get("/v1/customization-requests/{request_id}/decision")
@router.get("/v2/customization-requests/{request_id}/decision")
async def get_decision(request_id: UUID, request: Request):
    return await decision(request, request_id)


@router.get("/internal/v2/customization-requests/{request_id}/decision")
async def internal_decision(request_id: UUID, request: Request):
    service(request, {"orders", "eligibility", "pricing", "service-operations"})
    return await decision(request, request_id, internal=True)
