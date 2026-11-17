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
from .identity_store import sync_member
from .administration import responsibility_reducing

router = APIRouter(tags=["business-membership"])


class Reasoned(Contract):
    @field_validator("reason", "intervention_scope", check_fields=False)
    @classmethod
    def meaningful(cls, value):
        if value is None:
            return None
        value = value.strip()
        if len(value) < 5:
            raise ValueError("A meaningful reason or scope is required")
        return value


class Grant(Reasoned):
    business_id: UUID
    subject_id: UUID
    capabilities: list[
        Literal[
            "business.stock.write",
            "business.jobs.write",
            "business.records.read",
            "business.staff.manage",
        ]
    ] = Field(min_length=1, max_length=4)
    qualifications: list[str] = Field(default_factory=list, max_length=12)
    intervention_scope: str = Field(min_length=5, max_length=300)
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("qualifications")
    @classmethod
    def bounded(cls, value):
        value = [item.strip() for item in value]
        if any(not 2 <= len(item) <= 100 for item in value):
            raise ValueError("Bounded qualifications required")
        return value

    @field_validator("capabilities")
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate capability")
        return value


class Change(Reasoned):
    revision: int = Field(ge=1)
    state: Literal["active", "suspended", "revoked"]
    reason: str = Field(min_length=5, max_length=500)
    capabilities: (
        list[
            Literal[
                "business.stock.write",
                "business.jobs.write",
                "business.records.read",
                "business.staff.manage",
            ]
        ]
        | None
    ) = Field(default=None, min_length=1, max_length=4)
    qualifications: list[str] | None = Field(default=None, max_length=12)
    intervention_scope: str | None = Field(default=None, min_length=5, max_length=300)

    @field_validator("qualifications")
    @classmethod
    def bounded(cls, value):
        value = [item.strip() for item in value] if value is not None else None
        if value is not None and any(not 2 <= len(item) <= 100 for item in value):
            raise ValueError("Bounded qualifications required")
        return value

    @field_validator("capabilities")
    @classmethod
    def unique(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Duplicate capability")
        return value


def dto(row):
    return {
        key: str(row[key]) if key in {"id", "business_id", "subject_id"} else row[key]
        for key in (
            "id",
            "business_id",
            "subject_id",
            "capabilities",
            "qualifications",
            "intervention_scope",
            "state",
            "revision",
        )
    }


async def assert_business(tx, business_id, *, require_active=True):
    row = await tx.fetchrow(
        "SELECT state,kind,capabilities FROM l02_businesses WHERE id=$1 FOR SHARE",
        business_id,
    )
    if not row or (require_active and row["state"] != "active"):
        raise PublicError(
            "business_unavailable",
            "An active onboarded business is required.",
            status=409,
        )
    return row


def require_supported(business, capabilities):
    supported = set(business["capabilities"])
    if (
        "business.stock.write" in capabilities
        and "sales" not in supported
        or "business.jobs.write" in capabilities
        and not supported.intersection({"servicing", "customization"})
    ):
        raise PublicError(
            "business_capability_required",
            "The business does not support that capability.",
            status=409,
        )


@router.get("/v1/businesses/{business_id}/memberships")
async def members(
    business_id: UUID, request: Request, actor: CurrentPrincipal = Depends(principal)
):
    # Business admins may read only their represented business, never grant access.
    if "identity.membership.manage" not in actor.permissions:
        require_scope(actor, "business.staff.manage", business_id)
    async with request.app.state.pool.acquire() as tx:
        await assert_business(
            tx,
            business_id,
            require_active="identity.membership.manage" not in actor.permissions,
        )
        if "identity.membership.manage" not in actor.permissions:
            permitted = await tx.fetchval(
                """SELECT id FROM l02_memberships WHERE business_id=$1 AND subject_id=$2
                AND state='active' AND 'business.staff.manage'=ANY(capabilities)""",
                business_id,
                actor.actor.subject_id,
            )
            if not permitted:
                raise AccessDenied("Current organization membership required")
        rows = await tx.fetch(
            "SELECT * FROM l02_memberships WHERE business_id=$1 ORDER BY id LIMIT 100",
            business_id,
        )
    return {"items": [dto(row) for row in rows]}


@router.post("/v1/memberships")
async def grant(
    body: Grant,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
):
    require_scope(actor, "identity.membership.manage")
    if actor.actor.subject_id == body.subject_id:
        raise AccessDenied("A human cannot grant their own privileged membership")
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    async with unit_of_work(
        request.app.state.pool,
        lock_key="l02.membership-op:" + str(actor.actor.subject_id),
    ) as tx:
        await tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            "l02.business-target:" + str(body.business_id),
        )
        await lock_accounts(tx, actor.actor.subject_id, body.subject_id)
        await require_current(
            tx, request, "identity.membership.manage", actor.actor.subject_id
        )
        business = await assert_business(tx, body.business_id)
        old = await tx.fetchrow(
            "SELECT * FROM l02_membership_operations WHERE actor_id=$1 AND operation_key=$2",
            actor.actor.subject_id,
            key,
        )
        if old:
            if old["fingerprint"] != fingerprint:
                raise PublicError(
                    "idempotency_conflict", "Operation key already used.", status=409
                )
            return json.loads(old["result"])
        require_supported(business, body.capabilities)
        exists = await tx.fetchval(
            "SELECT id FROM l02_memberships WHERE business_id=$1 AND subject_id=$2",
            body.business_id,
            body.subject_id,
        )
        if exists:
            raise PublicError(
                "membership_exists",
                "Change the existing membership with its current revision.",
                status=409,
            )
        row = await tx.fetchrow(
            """INSERT INTO l02_memberships
            (id,business_id,subject_id,capabilities,qualifications,intervention_scope)
            VALUES($1,$2,$3,$4,$5,$6) RETURNING *""",
            uuid4(),
            body.business_id,
            body.subject_id,
            body.capabilities,
            body.qualifications,
            body.intervention_scope,
        )
        await tx.execute(
            """INSERT INTO l02_membership_history(membership_id,actor_id,revision,reason,state,snapshot)
            VALUES($1,$2,1,$3,'active',$4::jsonb)""",
            row["id"],
            actor.actor.subject_id,
            body.reason,
            json.dumps(dto(row)),
        )
        await sync_member(tx, row, business["kind"])
        result = dto(row)
        await tx.execute(
            "INSERT INTO l02_membership_operations VALUES($1,$2,$3,$4::jsonb)",
            actor.actor.subject_id,
            key,
            fingerprint,
            json.dumps(result),
        )
        await enqueue(
            tx,
            EventEnvelope(
                type="identity.membership-changed.v1",
                source="identity",
                subject=str(body.subject_id),
                request_id=request.state.request_id,
                data={
                    "subject_id": str(body.subject_id),
                    "business_id": str(body.business_id),
                    "state": "active",
                    "revision": 1,
                    "revoke_sessions": True,
                },
            ),
            ["catalog", "service-operations", "auction"],
        )
    return result


@router.patch("/v1/memberships/{membership_id}")
async def change(
    membership_id: UUID,
    body: Change,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
):
    require_scope(actor, "identity.membership.manage")
    fingerprint = hashlib.sha256(
        (str(membership_id) + body.model_dump_json()).encode()
    ).hexdigest()
    async with unit_of_work(
        request.app.state.pool,
        lock_key="l02.membership-op:" + str(actor.actor.subject_id),
    ) as tx:
        target = await tx.fetchrow(
            "SELECT business_id,subject_id FROM l02_memberships WHERE id=$1",
            membership_id,
        )
        if not target:
            raise PublicError("not_found", "Membership not found.", status=404)
        await tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            "l02.business-target:" + str(target["business_id"]),
        )
        await lock_accounts(tx, actor.actor.subject_id, target["subject_id"])
        await require_current(
            tx, request, "identity.membership.manage", actor.actor.subject_id
        )
        old = await tx.fetchrow(
            "SELECT * FROM l02_membership_operations WHERE actor_id=$1 AND operation_key=$2",
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
            "SELECT * FROM l02_memberships WHERE id=$1 FOR UPDATE", membership_id
        )
        if not row:
            raise PublicError("not_found", "Membership not found.", status=404)
        if actor.actor.subject_id == row["subject_id"]:
            raise AccessDenied("Self-intervention denied")
        if row["revision"] != body.revision:
            raise PublicError(
                "stale_revision", "Reload the current membership.", status=409
            )
        business = await assert_business(
            tx, row["business_id"], require_active=body.state == "active"
        )
        if body.state == "active":
            require_supported(
                business,
                body.capabilities
                if body.capabilities is not None
                else row["capabilities"],
            )
        # This endpoint has no current responsibility or replacement boundary.
        # Keep responsibility-reducing edits held until that boundary is available.
        if responsibility_reducing(row, body):
            raise PublicError(
                "responsibilities_unavailable",
                "Current responsibilities and replacement are required. / يلزم التحقق من المسؤوليات الحالية والبديل.",
                status=409,
            )
        row = await tx.fetchrow(
            """UPDATE l02_memberships SET state=$2,
            capabilities=COALESCE($3,capabilities),qualifications=COALESCE($4,qualifications),
            intervention_scope=COALESCE($5,intervention_scope),revision=revision+1,changed_at=now()
            WHERE id=$1 RETURNING *""",
            membership_id,
            body.state,
            body.capabilities,
            body.qualifications,
            body.intervention_scope,
        )
        await tx.execute(
            """INSERT INTO l02_membership_history(membership_id,actor_id,revision,reason,state,snapshot)
            VALUES($1,$2,$3,$4,$5,$6::jsonb)""",
            membership_id,
            actor.actor.subject_id,
            row["revision"],
            body.reason,
            body.state,
            json.dumps(dto(row)),
        )
        await sync_member(tx, row, business["kind"])
        result = dto(row)
        await tx.execute(
            "INSERT INTO l02_membership_operations VALUES($1,$2,$3,$4::jsonb)",
            actor.actor.subject_id,
            key,
            fingerprint,
            json.dumps(result),
        )
        await enqueue(
            tx,
            EventEnvelope(
                type="identity.membership-changed.v1",
                source="identity",
                subject=str(row["subject_id"]),
                request_id=request.state.request_id,
                data={
                    "subject_id": str(row["subject_id"]),
                    "business_id": str(row["business_id"]),
                    "state": body.state,
                    "revision": row["revision"],
                    "revoke_sessions": True,
                },
            ),
            ["catalog", "service-operations", "auction"],
        )
    return result


@router.get("/v2/businesses/{business_id}/memberships")
async def members_v2(business_id: UUID, request: Request,
                     actor: CurrentPrincipal = Depends(principal),
                     page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=25)):
    platform = "identity.membership.manage" in actor.permissions
    if not platform:
        require_scope(actor, "business.staff.manage", business_id)
    async with unit_of_work(request.app.state.pool) as tx:
        await tx.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await live_actor(tx, request, lock=True)
        if platform:
            await require_current(tx, request, "identity.membership.manage", actor.actor.subject_id)
        await assert_business(tx, business_id, require_active=not platform)
        if not platform and not await tx.fetchval(
            """SELECT id FROM l02_memberships WHERE business_id=$1 AND subject_id=$2
            AND state='active' AND 'business.staff.manage'=ANY(capabilities)""",
            business_id, actor.actor.subject_id):
            raise AccessDenied("Current business permission required / يلزم إذن حالي للنشاط التجاري")
        total = await tx.fetchval("SELECT count(*) FROM l02_memberships WHERE business_id=$1", business_id)
        rows = await tx.fetch(
            "SELECT * FROM l02_memberships WHERE business_id=$1 ORDER BY id LIMIT $2 OFFSET $3",
            business_id, page_size, (page - 1) * page_size)
    return {"items": [dto(row) for row in rows], "total": total, "page": page, "page_size": page_size}
