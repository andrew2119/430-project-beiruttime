import json
import os
from datetime import timedelta
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from bt_contracts.orders.allocation import RegisterWatch, ReserveWatch, FenceWatch, CustodyFact, Transition
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import require_scope
from bt_runtime.app.db import unit_of_work
from .dependencies import principal, service, quote, organization_principal
from .repository import command, audit, event, denied, order_view, watch_view
from .communications import reservation_notice

router = APIRouter(tags=["allocation-v1"])


def user_key(actor):
    return "user:" + str(actor.actor.subject_id)


def scoped(actor, row, permission):
    require_scope(actor, permission, row["organization_id"])


def readable(actor, row):
    if actor.actor.subject_id not in (row["buyer_id"], row["seller_id"]):
        scoped(actor, row, "orders.read")


@router.post("/internal/v1/watches/register")
async def register(body: RegisterWatch, request: Request, idempotency_key: str = Header(default="")):
    service(request, "catalog")

    async def apply(tx):
        # The physical id lock serializes new registrations as well as existing rows.
        await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "l08-watch:" + str(body.watch_id))
        await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "l08-listing:" + str(body.listing_id))
        existing = await tx.fetchrow("SELECT * FROM l08_watches WHERE id=$1 FOR UPDATE", body.watch_id)
        if existing:
            if any(existing[k] != v for k, v in body.model_dump().items() if k != "watch_id"):
                return denied("watch_already_registered")
            return {"status": "succeeded", "resource_id": str(body.watch_id), "watch": watch_view(existing)}
        if await tx.fetchval("SELECT 1 FROM l08_watches WHERE listing_id=$1", body.listing_id):
            return denied("listing_already_registered")
        row = await tx.fetchrow(
            """INSERT INTO l08_watches(id,listing_id,seller_id,organization_id,listing_revision,sale_mode,is_demo)
            VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
            body.watch_id,
            body.listing_id,
            body.seller_id,
            body.organization_id,
            body.listing_revision,
            body.sale_mode,
            body.is_demo,
        )
        await audit(tx, body.watch_id, "service:catalog", "register", "Listing publication", 1)
        await event(tx, request, "watch-registered", body.watch_id, 1)
        return {"status": "succeeded", "resource_id": str(body.watch_id), "watch": watch_view(row)}

    return await command(
        request.app.state.pool,
        "service:catalog",
        idempotency_key,
        "register",
        body.model_dump(),
        apply,
        request_id=request.state.request_id,
    )


@router.get("/v1/watches/{watch_id}/availability")
async def availability(watch_id: UUID, request: Request):
    row = await request.app.state.pool.fetchrow("SELECT * FROM l08_watches WHERE id=$1", watch_id)
    if not row:
        raise HTTPException(404)
    return watch_view(row)


@router.get("/v1/listings/{listing_id}/availability")
async def listing_availability(listing_id: UUID, request: Request):
    row = await request.app.state.pool.fetchrow("SELECT * FROM l08_watches WHERE listing_id=$1", listing_id)
    if not row:
        raise HTTPException(404)
    return watch_view(row)


@router.get("/internal/v1/watches/{watch_id}/fence")
async def fence_read(watch_id: UUID, source_id: UUID, request: Request):
    service(request, {"catalog", "auction"})
    row = await request.app.state.pool.fetchrow("SELECT * FROM l08_watches WHERE id=$1", watch_id)
    if not row:
        raise HTTPException(404)
    return {**watch_view(row), "source_matches": row["source_id"] == source_id}


@router.get("/internal/v1/operations/{operation_id}")
async def service_operation(operation_id: UUID, request: Request):
    caller = service(request, {"catalog", "auction"})
    value = await request.app.state.pool.fetchval(
        "SELECT result FROM l08_operations WHERE id=$1 AND actor_key=$2", operation_id, "service:" + caller
    )
    if value is None:
        raise HTTPException(404)
    return json.loads(value)


@router.post("/v1/reservations")
async def reserve(
    body: ReserveWatch, request: Request, actor=Depends(principal), idempotency_key: str = Header(default="")
):
    if "buyer" not in actor.roles:
        raise AccessDenied("Buyer permission required")
    actor_key = user_key(actor)

    async def apply(tx):
        validated = await quote(request, body.quote_id)
        row = await tx.fetchrow("SELECT * FROM l08_watches WHERE id=$1 FOR UPDATE", body.watch_id)
        if not row:
            return denied("watch_unknown")
        if row["seller_id"] == actor.actor.subject_id:
            return denied("self_purchase")
        if row["status"] != "available":
            return denied("watch_unavailable")
        if row["revision"] != body.expected_revision:
            return denied("stale_revision")
        if row["sale_mode"] != "fixed":
            return denied("sale_mode_unavailable")
        now = await tx.fetchval("SELECT clock_timestamp()")
        if (
            validated.quote_id != body.quote_id
            or validated.buyer_id != actor.actor.subject_id
            or validated.listing_id != row["listing_id"]
            or validated.listing_revision != row["listing_revision"]
        ):
            return denied("quote_mismatch")
        if now >= validated.expires_at:
            return denied("quote_expired")
        ttl = max(60, min(86400, int(os.environ.get("BT_UNPAID_FIXED_SECONDS", "900"))))
        deadline = min(validated.expires_at, now + timedelta(seconds=ttl))
        order_id = uuid4()
        order = await tx.fetchrow(
            """INSERT INTO l08_orders(id,watch_id,buyer_id,seller_id,organization_id,quote_id,
            state,currency,total_minor,deadline,listing_id,is_demo) VALUES($1,$2,$3,$4,$5,$6,'awaiting_payment',$7,$8,$9,$10,$11) RETURNING *""",
            order_id,
            body.watch_id,
            actor.actor.subject_id,
            row["seller_id"],
            row["organization_id"],
            body.quote_id,
            validated.currency,
            validated.total_minor,
            deadline,
            row["listing_id"],
            row["is_demo"],
        )
        await tx.execute(
            "UPDATE l08_watches SET status='reserved',source_id=$2,revision=revision+1 WHERE id=$1",
            body.watch_id,
            order_id,
        )
        await audit(tx, order_id, actor_key, "reserve", "Fixed-price reservation", 1)
        await audit(tx, body.watch_id, actor_key, "reserve", "Exclusive physical commitment", row["revision"] + 1)
        await event(tx, request, "reserved", order_id, 1)
        await reservation_notice(tx, request, order)
        return {"status": "succeeded", "resource_id": str(order_id), "order": order_view(order)}

    return await command(
        request.app.state.pool,
        actor_key,
        idempotency_key,
        "reserve",
        body.model_dump(),
        apply,
        request_id=request.state.request_id,
    )


@router.post("/internal/v1/watches/{watch_id}/fences")
async def fence(watch_id: UUID, body: FenceWatch, request: Request, idempotency_key: str = Header(default="")):
    service(request, "auction")

    async def apply(tx):
        row = await tx.fetchrow("SELECT * FROM l08_watches WHERE id=$1 FOR UPDATE", watch_id)
        if not row:
            return denied("watch_unknown")
        if row["sale_mode"] != "auction":
            return denied("sale_mode_unavailable")
        if row["status"] == "fenced" and row["source_id"] == body.source_id:
            return {"status": "succeeded", "resource_id": str(watch_id), "watch": watch_view(row)}
        if row["status"] != "available":
            return denied("watch_unavailable")
        if row["revision"] != body.expected_revision:
            return denied("stale_revision")
        row = await tx.fetchrow(
            "UPDATE l08_watches SET status='fenced',source_id=$2,revision=revision+1 WHERE id=$1 RETURNING *",
            watch_id,
            body.source_id,
        )
        await audit(tx, watch_id, "service:auction", "fence", body.reason, row["revision"])
        await event(tx, request, "fenced", watch_id, row["revision"])
        return {"status": "succeeded", "resource_id": str(watch_id), "watch": watch_view(row)}

    return await command(
        request.app.state.pool,
        "service:auction",
        idempotency_key,
        "fence",
        {"watch_id": watch_id, **body.model_dump()},
        apply,
        request_id=request.state.request_id,
    )


@router.get("/v1/operations/{operation_id}")
async def operation(operation_id: UUID, request: Request, actor=Depends(principal)):
    value = await request.app.state.pool.fetchval(
        "SELECT result FROM l08_operations WHERE id=$1 AND actor_key=$2", operation_id, user_key(actor)
    )
    if value is None:
        raise HTTPException(404)
    return json.loads(value)


@router.get("/v1/me/reservations")
async def buyer_reservations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    cursor: UUID | None = None,
    actor=Depends(principal),
):
    if "buyer" not in actor.roles:
        raise AccessDenied("Buyer permission required")
    if cursor is not None and not await request.app.state.pool.fetchval(
        "SELECT 1 FROM l08_orders WHERE id=$1 AND buyer_id=$2", cursor, actor.actor.subject_id
    ):
        raise PublicError("invalid_cursor", "Reload the first reservations page.", status=422)
    rows = await request.app.state.pool.fetch(
        """SELECT * FROM l08_orders o WHERE buyer_id=$1 AND state='awaiting_payment' AND deadline>clock_timestamp()
        AND ($2::uuid IS NULL OR (o.created_at,o.id)<(SELECT created_at,id FROM l08_orders WHERE id=$2 AND buyer_id=$1))
        ORDER BY created_at DESC,id DESC LIMIT $3""",
        actor.actor.subject_id,
        cursor,
        limit + 1,
    )
    items = [
        {
            "reservation_id": str(row["id"]),
            "listing_id": str(row["listing_id"]),
            "buyer_id": str(row["buyer_id"]),
            "state": row["state"],
            "total_minor": row["total_minor"],
            "currency": row["currency"],
            "revision": row["revision"],
            "expires_at": row["deadline"].isoformat(),
            "is_demo": row["is_demo"],
        }
        for row in rows[:limit]
    ]
    return {"items": items, "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None}


@router.get("/v1/orders")
async def orders(request: Request, actor=Depends(principal)):
    # Only own buyer/seller records. Operator access is resource-scoped, never a global bypass.
    rows = await request.app.state.pool.fetch(
        """SELECT * FROM l08_orders WHERE buyer_id=$1 OR seller_id=$1
        ORDER BY created_at DESC,id LIMIT 100""",
        actor.actor.subject_id,
    )
    return {"items": [order_view(row) for row in rows]}


@router.get("/v1/orders/{order_id}")
async def order(order_id: UUID, request: Request, actor=Depends(principal)):
    row = await request.app.state.pool.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order_id)
    if not row:
        raise HTTPException(404)
    readable(actor, row)
    records = await request.app.state.pool.fetch(
        "SELECT action,reason,revision,occurred_at FROM l08_audit WHERE resource_id=$1 AND action IN ('reserve','payment-hold','expiry-fence','pre-release-intake') ORDER BY id",
        order_id,
    )
    return {"order": order_view(row), "history": [dict(r) for r in records]}


@router.post("/v1/orders/{order_id}/transitions")
async def transition(
    order_id: UUID,
    body: Transition,
    request: Request,
    actor=Depends(principal),
    idempotency_key: str = Header(default=""),
):
    current = await request.app.state.pool.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order_id)
    if not current:
        raise HTTPException(404)
    scoped(actor, current, "orders.manage")

    async def apply(tx):
        row = await tx.fetchrow("SELECT * FROM l08_orders WHERE id=$1 FOR UPDATE", order_id)
        if not row:
            raise HTTPException(404)
        scoped(actor, row, "orders.manage")
        if row["revision"] != body.expected_revision:
            return denied("stale_revision")
        if body.state != "payment_unknown" or row["state"] != "awaiting_payment":
            return denied("transition_unreleased")
        row = await tx.fetchrow(
            "UPDATE l08_orders SET state='payment_unknown',revision=revision+1 WHERE id=$1 RETURNING *", order_id
        )
        await audit(tx, order_id, user_key(actor), "payment-hold", body.reason, row["revision"])
        await event(tx, request, "state-changed", order_id, row["revision"])
        return {"status": "succeeded", "resource_id": str(order_id), "order": order_view(row)}

    return await command(
        request.app.state.pool,
        user_key(actor),
        idempotency_key,
        "transition",
        {"order_id": order_id, **body.model_dump()},
        apply,
        request_id=request.state.request_id,
    )


@router.post("/v1/orders/{order_id}/intake")
async def intake(
    order_id: UUID,
    body: CustodyFact,
    request: Request,
    actor=Depends(principal),
    idempotency_key: str = Header(default=""),
):
    current = await request.app.state.pool.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order_id)
    if not current:
        raise HTTPException(404)
    scoped(actor, current, "orders.intake")

    async def apply(tx):
        row = await tx.fetchrow("SELECT * FROM l08_orders WHERE id=$1 FOR UPDATE", order_id)
        if not row:
            raise HTTPException(404)
        scoped(actor, row, "orders.intake")
        if row["revision"] != body.expected_revision:
            return denied("stale_revision")
        now = await tx.fetchval("SELECT clock_timestamp()")
        if body.occurred_at > now or any(not a.strip() or len(a) > 200 for a in body.accessories):
            return denied("invalid_intake")
        revision = row["revision"] + 1
        fact_id = uuid4()
        await tx.execute(
            """INSERT INTO l08_intake(id,order_id,actor_id,actual_watch,accessories,location,condition,occurred_at,revision)
            VALUES($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9)""",
            fact_id,
            order_id,
            actor.actor.subject_id,
            body.actual_watch,
            json.dumps(body.accessories),
            body.location,
            body.condition,
            body.occurred_at,
            revision,
        )
        await tx.execute("UPDATE l08_orders SET revision=$2 WHERE id=$1", order_id, revision)
        await audit(tx, order_id, user_key(actor), "pre-release-intake", body.reason, revision)
        await event(tx, request, "intake-recorded", order_id, revision)
        return {"status": "succeeded", "resource_id": str(fact_id), "revision": revision, "final_handover": False}

    return await command(
        request.app.state.pool,
        user_key(actor),
        idempotency_key,
        "intake",
        {"order_id": order_id, **body.model_dump()},
        apply,
        request_id=request.state.request_id,
    )


@router.get("/v1/custody/receipts/{receipt_id}")
async def custody_receipt(receipt_id: UUID, request: Request, actor=Depends(principal)):
    fact = await request.app.state.pool.fetchrow(
        """SELECT i.*,o.organization_id FROM l08_intake i
        JOIN l08_orders o ON o.id=i.order_id WHERE i.id=$1""",
        receipt_id,
    )
    if not fact:
        raise HTTPException(404)
    if fact["organization_id"] is None:
        raise PublicError(
            "custody_not_business_scoped", "This fact is not an official-business custody receipt.", status=409
        )
    selected = await organization_principal(request, fact["organization_id"])
    if selected.actor.subject_id != actor.actor.subject_id:
        raise AccessDenied("Identity scope changed")
    allowed = False
    for permission in ("orders.intake", "intake.read", "intake.write"):
        try:
            require_scope(selected, permission, fact["organization_id"])
            allowed = True
            break
        except AccessDenied:
            pass
    if not allowed:
        raise AccessDenied("Current custody scope denied")
    async with unit_of_work(request.app.state.pool) as tx:
        await tx.fetchrow("SELECT id FROM l08_orders WHERE id=$1 FOR SHARE", fact["order_id"])
        latest = await tx.fetchval(
            "SELECT id FROM l08_intake WHERE order_id=$1 ORDER BY revision DESC LIMIT 1", fact["order_id"]
        )
        if latest != receipt_id:
            raise PublicError("custody_receipt_stale", "A newer custody fact exists.", status=409)
        await audit(
            tx,
            fact["order_id"],
            user_key(selected),
            "custody-proof-read",
            "Scoped technical-intake receipt verification",
            fact["revision"],
        )
        return {
            "id": str(receipt_id),
            "order_id": str(fact["order_id"]),
            "organization_id": str(fact["organization_id"]),
            "received_at": fact["occurred_at"].isoformat(),
            "revision": fact["revision"],
            "valid": True,
        }


@router.get("/v1/orders/{order_id}/intake")
async def intake_read(order_id: UUID, request: Request, actor=Depends(principal)):
    row = await request.app.state.pool.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order_id)
    if not row:
        raise HTTPException(404)
    scoped(actor, row, "orders.intake")
    rows = await request.app.state.pool.fetch(
        "SELECT * FROM l08_intake WHERE order_id=$1 ORDER BY recorded_at,id LIMIT 100", order_id
    )
    return {"items": [{**dict(r), "accessories": json.loads(r["accessories"])} for r in rows]}
