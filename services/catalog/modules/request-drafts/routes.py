import asyncio
import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from bt_contracts.catalog.request_drafts import DraftInput, DraftUpdate
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from .dependencies import principal, read
from .configurations import bind, snapshot, safe_intent
from . import directory

router = APIRouter(tags=["private-request-drafts-v1"])


def view(row):
    content = json.loads(row["content"])
    content.pop("configuration_snapshot", None)
    content.setdefault("configuration_id", None)
    content.setdefault("configuration_revision", None)
    return {
        **content,
        "id": str(row["id"]),
        "revision": row["revision"],
        "updated_at": row["updated_at"].isoformat(),
        "status": "draft",
        "approved": False,
        "payment_authority": False,
    }


async def owned(pool, draft_id, owner_id):
    row = await pool.fetchrow("SELECT * FROM l08_request_drafts WHERE id=$1 AND owner_id=$2", draft_id, owner_id)
    if not row:
        raise HTTPException(404)
    return row


async def save(request, actor, key, body, draft_id=None):
    if not key or len(key) > 100 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise PublicError("idempotency_required", "Provide one stable Idempotency-Key.", status=422)
    owner_id = actor.actor.subject_id
    content = body.model_dump(mode="json")
    revision = content.pop("expected_revision", None)
    digest = hashlib.sha256(
        json.dumps(
            {"id": str(draft_id), "revision": revision, "content": content}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    async with unit_of_work(request.app.state.pool, lock_key="l08-draft-op:" + str(owner_id) + ":" + key) as tx:
        prior = await tx.fetchrow(
            "SELECT digest,result FROM l08_draft_operations WHERE owner_id=$1 AND operation_key=$2", owner_id, key
        )
        if prior:
            if prior["digest"] != digest:
                raise PublicError("idempotency_conflict", "This operation key has different content.", status=409)
            return json.loads(prior["result"])
        content = await bind(request, content)
        if draft_id is None:
            row = await tx.fetchrow(
                "INSERT INTO l08_request_drafts(id,owner_id,content) VALUES($1,$2,$3::jsonb) RETURNING *",
                uuid4(),
                owner_id,
                json.dumps(content),
            )
            action = "created"
        else:
            row = await tx.fetchrow(
                "SELECT * FROM l08_request_drafts WHERE id=$1 AND owner_id=$2 FOR UPDATE", draft_id, owner_id
            )
            if not row:
                raise HTTPException(404)
            if row["revision"] != revision:
                raise PublicError("stale_revision", "A newer draft exists. Reload before saving.", status=409)
            row = await tx.fetchrow(
                "UPDATE l08_request_drafts SET content=$3::jsonb,revision=revision+1,updated_at=clock_timestamp() WHERE id=$1 AND owner_id=$2 RETURNING *",
                draft_id,
                owner_id,
                json.dumps(content),
            )
            action = "updated"
        await tx.execute(
            "INSERT INTO l08_draft_audit(draft_id,actor_id,action,revision) VALUES($1,$2,$3,$4)",
            row["id"],
            owner_id,
            action,
            row["revision"],
        )
        await enqueue(
            tx,
            EventEnvelope(
                type="catalog.request-draft-saved.v1",
                source="catalog",
                subject=str(row["id"]),
                request_id=request.state.request_id,
                data={"resource_id": str(row["id"]), "revision": row["revision"]},
            ),
            ["communications"],
        )
        result = {
            "id": str(uuid4()),
            "status": "succeeded",
            "resource_id": str(row["id"]),
            "request_id": request.state.request_id,
            "draft": view(row),
        }
        await tx.execute(
            "INSERT INTO l08_draft_operations(id,owner_id,operation_key,digest,result) VALUES($1,$2,$3,$4,$5::jsonb)",
            UUID(result["id"]),
            owner_id,
            key,
            digest,
            json.dumps(result),
        )
        return result


@router.post("/v1/request-drafts")
async def create(
    body: DraftInput, request: Request, actor=Depends(principal), idempotency_key: str = Header(default="")
):
    return await save(request, actor, idempotency_key, body)


@router.patch("/v1/request-drafts/{draft_id}")
async def update(
    draft_id: UUID,
    body: DraftUpdate,
    request: Request,
    actor=Depends(principal),
    idempotency_key: str = Header(default=""),
):
    return await save(request, actor, idempotency_key, body, draft_id)


@router.get("/v1/request-draft-configurations/{configuration_id}")
async def configuration_intent(configuration_id: UUID, revision: int, request: Request, actor=Depends(principal)):
    if not 1 <= revision <= 2147483647:
        raise PublicError("invalid_revision", "Choose a current configuration revision.", status=422)
    return safe_intent(await snapshot(request, configuration_id, revision))


@router.get("/v1/request-draft-catalogue")
async def catalogue(
    request: Request,
    purpose: Literal["customization", "servicing"] = "customization",
    after: UUID | None = None,
    actor=Depends(principal),
):
    return await directory.catalogue(request, purpose, after)


@router.get("/v1/request-drafts")
async def drafts(request: Request, actor=Depends(principal)):
    rows = await request.app.state.pool.fetch(
        "SELECT * FROM l08_request_drafts WHERE owner_id=$1 ORDER BY updated_at DESC,id LIMIT 100",
        actor.actor.subject_id,
    )
    return {"items": [view(row) for row in rows]}


@router.get("/v1/request-drafts/{draft_id}")
async def draft(draft_id: UUID, request: Request, actor=Depends(principal)):
    return view(await owned(request.app.state.pool, draft_id, actor.actor.subject_id))


@router.get("/v1/request-drafts/{draft_id}/readiness")
async def readiness(draft_id: UUID, request: Request, actor=Depends(principal)):
    current = view(await owned(request.app.state.pool, draft_id, actor.actor.subject_id))
    brand_id = current["brand_id"]
    if brand_id:
        purpose = "customization" if current["kind"] == "customization" else "servicing"
        if purpose == "customization":
            brand, options = await asyncio.gather(
                directory.current(request, brand_id, purpose),
                read(request, "options", f"/v1/brand-options/brands/{brand_id}"),
            )
        else:
            brand = await directory.current(request, brand_id, purpose)
            options = {"status": "not_applicable"}
        # Staff-only intake records are not a buyer-safe request-bound readiness contract.
        intake = {"status": "unavailable"}
    else:
        brand = options = intake = {"status": "not_selected"}
    configuration = {"status": "not_selected"}
    if current.get("configuration_id"):
        try:
            configuration = {
                "status": "available",
                "data": safe_intent(
                    await snapshot(request, current["configuration_id"], current["configuration_revision"])
                ),
            }
        except PublicError as error:
            configuration = {"status": "unavailable", "code": error.code}
    return {
        "draft": current,
        "brand": brand,
        "options": options,
        "intake": intake,
        "configuration": configuration,
        "sections": {
            key: {"status": "unavailable", "reason": reason}
            for key, reason in {
                "quote": "No formal quote has been issued for this draft.",
                "consent": "No consent receipt is bound to this draft.",
                "work": "A draft is not an approved or accepted job.",
                "quality": "No completed work or quality result exists.",
                "collection": "No paid and checked release is authorized.",
            }.items()
        },
    }


@router.post("/v1/request-drafts/{draft_id}/actions/{action}")
async def future_action(
    draft_id: UUID,
    action: Literal["submit", "approve", "pay", "start", "complete", "collect"],
    request: Request,
    actor=Depends(principal),
):
    await owned(request.app.state.pool, draft_id, actor.actor.subject_id)
    raise PublicError("capability_unreleased", "This draft cannot authorize submission, payment or work.", status=409)


@router.get("/v1/request-draft-operations/{operation_id}")
async def operation(operation_id: UUID, request: Request, actor=Depends(principal)):
    result = await request.app.state.pool.fetchval(
        "SELECT result FROM l08_draft_operations WHERE id=$1 AND owner_id=$2", operation_id, actor.actor.subject_id
    )
    if result is None:
        raise HTTPException(404)
    return json.loads(result)
