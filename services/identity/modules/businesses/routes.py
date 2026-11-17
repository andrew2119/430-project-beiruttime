import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field, field_validator
from bt_contracts_core.models import Contract, EventEnvelope
from bt_contracts_core.errors import PublicError
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import CurrentPrincipal, require_scope
from service_app.identity import lock_accounts
from .capabilities import CapabilityDeclaration
from .security import principal, require_current
from .identity_store import affected_subjects, sync_business

router = APIRouter(prefix="/v1/businesses", tags=["official-businesses"])
CAPABILITIES = {"sales", "customization", "servicing"}


class Onboard(Contract):
    legal_name: str = Field(min_length=2, max_length=180)
    public_name: str = Field(min_length=2, max_length=120)
    kind: Literal["dealer", "brand"]
    capabilities: list[Literal["sales", "customization", "servicing"]] = Field(
        min_length=1, max_length=3
    )
    assurance_reference: str = Field(min_length=5, max_length=160)
    reason: str = Field(min_length=5, max_length=500)
    sample: bool = False
    confirmation_ref: UUID | None = None
    confirmed_scope: list[Literal["sales", "customization", "servicing"]] = Field(
        default_factory=list, max_length=3
    )

    @field_validator("legal_name", "public_name", "assurance_reference", "reason")
    @classmethod
    def trim(cls, value):
        if value != value.strip() or not value.strip():
            raise ValueError("Remove surrounding whitespace")
        return value

    @field_validator("capabilities")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate capability")
        return value


class Change(Contract):
    revision: int = Field(ge=1)
    state: Literal["active", "revoked"]
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        value = value.strip()
        if len(value) < 5:
            raise ValueError("A meaningful decision reason is required")
        return value


def require_activation(identity, revision, sample, capabilities, confirmation_ref, confirmed_scope):
    declaration = CapabilityDeclaration(
        identity, revision, frozenset(capabilities), sample,
        confirmation_ref, frozenset(confirmed_scope),
    )
    if (not declaration.permits(identity, revision, set(capabilities), synthetic_release=sample)
            or (not sample and set(confirmed_scope) != set(capabilities))):
        raise PublicError(
            "business_confirmation_required",
            "Record business confirmation of the exact offering scope before activation. / "
            "سجّل تأكيد النشاط التجاري لنطاق العروض المحدد قبل التفعيل.",
            status=409,
        )


def public(row):
    return {
        "id": str(row["id"]),
        "public_name": row["public_name"],
        "kind": row["kind"],
        "capabilities": row["capabilities"],
        "state": row["state"],
        "revision": row["revision"],
        "sample": row["sample"],
        "platform_onboarded": row["state"] == "active",
        "authenticated_business": row["state"] == "active",
        "independent_watch_authentication_required": False,
    }


async def operation(tx, actor, key, body):
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    old = await tx.fetchrow(
        "SELECT * FROM l02_business_operations WHERE actor_id=$1 AND operation_key=$2",
        actor,
        key,
    )
    if old and old["fingerprint"] != fingerprint:
        raise PublicError(
            "idempotency_conflict",
            "Use a new operation key for changed fields.",
            status=409,
        )
    return fingerprint, json.loads(old["result"]) if old else None


@router.get("")
async def directory(request: Request):
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch(
            "SELECT * FROM l02_businesses WHERE state='active' ORDER BY public_name LIMIT 100"
        )
    return {"items": [public(row) for row in rows]}


@router.get("/manage/records")
async def managed_records(
    request: Request, actor: CurrentPrincipal = Depends(principal)
):
    require_scope(actor, "identity.businesses.manage")
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch(
            "SELECT * FROM l02_businesses ORDER BY updated_at DESC LIMIT 100"
        )
    return {"items": [public(row) for row in rows]}


@router.get("/{business_id}")
async def detail(business_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM l02_businesses WHERE id=$1", business_id)
    if not row:
        raise PublicError("not_found", "Business not found.", status=404)
    return public(row)


@router.post("")
async def onboard(
    body: Onboard,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
):
    require_scope(actor, "identity.businesses.manage")
    if body.kind == "dealer" and "customization" in body.capabilities:
        raise PublicError(
            "brand_required",
            "Only an official brand can accept customization.",
            status=422,
        )
    subject = actor.actor.subject_id
    async with unit_of_work(
        request.app.state.pool, lock_key="l02.business:" + str(subject)
    ) as tx:
        await lock_accounts(tx, subject)
        await require_current(tx, request, "identity.businesses.manage", subject)
        fingerprint, old = await operation(tx, subject, key, body)
        if old:
            return old
        identity = uuid4()
        require_activation(identity, 1, body.sample, body.capabilities,
                           body.confirmation_ref, body.confirmed_scope)
        row = await tx.fetchrow(
            """INSERT INTO l02_businesses
            (id,legal_name,public_name,kind,capabilities,assurance_reference,sample,created_by,
             confirmation_ref,confirmed_scope,confirmed_by,confirmed_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                   CASE WHEN $9::uuid IS NOT NULL THEN now() ELSE NULL END) RETURNING *""",
            identity,
            body.legal_name,
            body.public_name,
            body.kind,
            body.capabilities,
            body.assurance_reference,
            body.sample,
            subject,
            None if body.sample else body.confirmation_ref,
            [] if body.sample else body.confirmed_scope,
            None if body.sample else subject,
        )
        await tx.execute(
            """INSERT INTO l02_business_history(business_id,actor_id,revision,action,reason)
            VALUES($1,$2,1,'onboarded',$3)""",
            identity,
            subject,
            body.reason,
        )
        result = public(row)
        await tx.execute(
            "INSERT INTO l02_business_operations VALUES($1,$2,$3,$4::jsonb,now())",
            subject,
            key,
            fingerprint,
            json.dumps(result),
        )
        await enqueue(
            tx,
            EventEnvelope(
                type="identity.business-onboarded.v1",
                source="identity",
                subject=str(identity),
                request_id=request.state.request_id,
                data={
                    "business_id": str(identity),
                    "kind": body.kind,
                    "revision": 1,
                    "sample": body.sample,
                },
            ),
            ["catalog", "service-operations"],
        )
    return result


@router.patch("/{business_id}")
async def change(
    business_id: UUID,
    body: Change,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
):
    require_scope(actor, "identity.businesses.manage")
    async with unit_of_work(
        request.app.state.pool, lock_key="l02.business:" + str(actor.actor.subject_id)
    ) as tx:
        await tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            "l02.business-target:" + str(business_id),
        )
        subjects = await affected_subjects(tx, business_id)
        await lock_accounts(tx, actor.actor.subject_id, *subjects)
        await require_current(
            tx, request, "identity.businesses.manage", actor.actor.subject_id
        )
        # Bind the idempotency fingerprint to the resource as well as the payload.
        command = body.model_copy()
        fingerprint = hashlib.sha256(
            (str(business_id) + command.model_dump_json()).encode()
        ).hexdigest()
        old = await tx.fetchrow(
            "SELECT * FROM l02_business_operations WHERE actor_id=$1 AND operation_key=$2",
            actor.actor.subject_id,
            key,
        )
        if old:
            if old["fingerprint"] != fingerprint:
                raise PublicError(
                    "idempotency_conflict", "Operation key already used.", status=409
                )
            return json.loads(old["result"])
        row = await tx.fetchrow(
            "SELECT * FROM l02_businesses WHERE id=$1 FOR UPDATE", business_id
        )
        if not row:
            raise PublicError("not_found", "Business not found.", status=404)
        if row["revision"] != body.revision:
            raise PublicError(
                "stale_revision",
                "Reload the current business before changing it.",
                status=409,
            )
        if body.state == "active":
            require_activation(business_id, row["revision"], row["sample"], row["capabilities"],
                               row["confirmation_ref"], row["confirmed_scope"])
        row = await tx.fetchrow(
            """UPDATE l02_businesses SET state=$2,revision=revision+1,updated_at=now()
            WHERE id=$1 RETURNING *""",
            business_id,
            body.state,
        )
        await tx.execute(
            """INSERT INTO l02_business_history(business_id,actor_id,revision,action,reason)
            VALUES($1,$2,$3,$4,$5)""",
            business_id,
            actor.actor.subject_id,
            row["revision"],
            body.state,
            body.reason,
        )
        await sync_business(tx, row)
        result = public(row)
        await tx.execute(
            "INSERT INTO l02_business_operations VALUES($1,$2,$3,$4::jsonb,now())",
            actor.actor.subject_id,
            key,
            fingerprint,
            json.dumps(result),
        )
        await enqueue(
            tx,
            EventEnvelope(
                type="identity.business-status-changed.v1",
                source="identity",
                subject=str(business_id),
                request_id=request.state.request_id,
                data={
                    "business_id": str(business_id),
                    "state": body.state,
                    "revision": row["revision"],
                },
            ),
            ["catalog", "service-operations", "auction"],
        )
    return result


legacy_router = router
router = APIRouter()
router.include_router(legacy_router)


@router.get("/v2/businesses")
async def directory_v2(request: Request, page: int = Query(1, ge=1),
                       page_size: int = Query(25, ge=1, le=25)):
    async with unit_of_work(request.app.state.pool) as tx:
        await tx.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        total = await tx.fetchval("SELECT count(*) FROM l02_businesses WHERE state='active'")
        rows = await tx.fetch(
            "SELECT * FROM l02_businesses WHERE state='active' ORDER BY public_name,id LIMIT $1 OFFSET $2",
            page_size, (page - 1) * page_size)
    return {"items": [public(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/v2/businesses/manage/records")
async def records_v2(request: Request, actor: CurrentPrincipal = Depends(principal),
                     page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=25)):
    async with unit_of_work(request.app.state.pool) as tx:
        await tx.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await require_current(tx, request, "identity.businesses.manage", actor.actor.subject_id)
        total = await tx.fetchval("SELECT count(*) FROM l02_businesses")
        rows = await tx.fetch("SELECT * FROM l02_businesses ORDER BY updated_at DESC,id LIMIT $1 OFFSET $2",
                              page_size, (page - 1) * page_size)
    return {"items": [public(row) for row in rows], "total": total, "page": page, "page_size": page_size}
