from datetime import timedelta
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, Query, Request
from bt_contracts.orders.allocation import ReserveWatch
from bt_contracts.orders.allocation.v2 import (
    Commitment,
    Allocate,
    FinishEdit,
    EditOperationResolution,
)
from bt_contracts_core.errors import AccessDenied, PublicError
from service_app.orders_dependencies import principal, service
from service_app.orders_kernel import (
    command,
    operation,
    lock_watch,
    watch_fact,
    order_fact,
    audit,
    record_fact,
)
from service_app.exact_quote import (
    upstream,
    exact_snapshot,
    retain,
    current_quote,
    retained_snapshot,
)

router = APIRouter(tags=["commitment-v2"])


def denied(code, row=None):
    return {
        "status": "denied",
        "code": code,
        **({"watch": watch_fact(row)} if row else {}),
    }


def require_key(body, key):
    if body.operation_key != key:
        raise PublicError(
            "operation_key_mismatch",
            "Use the same operation key in the header and body.",
            status=422,
        )


@router.get("/internal/v2/operations/{operation_key}")
async def lookup(operation_key: str, request: Request):
    caller = service(request, {"catalog", "auction", "pricing"})
    result = await operation(request.app.state.pool, "service:" + caller, operation_key)
    if result is None:
        raise PublicError(
            "operation_unknown",
            "Retry the original command with the same key.",
            status=404,
        )
    return result


@router.get(
    "/internal/v2/listing-edit-operations/{source_id}",
    response_model=EditOperationResolution,
)
async def edit_resolution(
    source_id: UUID,
    request: Request,
    operation_key: str = Query(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    ),
):
    service(request, "auction")
    row = await request.app.state.pool.fetchrow(
        """SELECT o.id,o.idempotency_key AS operation_key,b.source_id,b.watch_id,b.listing_id,
        b.listing_revision,b.expected_revision,o.result->>'status' AS status
        FROM l13_listing_edit_bindings b JOIN l08_operations o ON o.id=b.operation_id
        WHERE o.actor_key='service:catalog' AND o.idempotency_key=$1 AND b.source_id=$2
        AND o.result->>'status' IN ('succeeded','denied')""",
        operation_key,
        source_id,
    )
    if row is None:
        raise PublicError(
            "operation_unknown",
            "No exact retained Catalog edit outcome exists.",
            status=404,
        )
    return {**dict(row), "producer": "catalog", "kind": "edit"}


@router.get("/internal/v2/watches/{watch_id}")
async def read_watch(watch_id: UUID, request: Request):
    service(request, {"catalog", "auction", "pricing"})
    row = await request.app.state.pool.fetchrow(
        "SELECT * FROM l08_watches WHERE id=$1", watch_id
    )
    if row is None:
        raise PublicError("watch_unknown", "Watch not found.", status=404)
    return watch_fact(row)


@router.post("/internal/v2/commitments")
async def commitment(
    body: Commitment, request: Request, idempotency_key: str = Header(default="")
):
    caller = service(
        request, "catalog" if body.kind in {"edit", "withdraw"} else "auction"
    )
    require_key(body, idempotency_key)

    async def apply(tx):
        row = await lock_watch(tx, body.watch_id)
        if (
            row["listing_id"] != body.listing_id
            or row["listing_revision"] != body.listing_revision
        ):
            return denied("listing_revision_mismatch", row)
        # Same canonical source can reconcile using a new transport call, never release.
        if (
            body.kind == "first_bid"
            and row["status"] == "fenced"
            and row["source_id"] == body.source_id
            and row["auction_committed"]
        ):
            return {"status": "succeeded", "watch": watch_fact(row)}
        if row["revision"] != body.expected_revision:
            return denied("stale_revision", row)
        ordinary = row["status"] == "available"
        empty_auction = (
            row["status"] == "fenced"
            and not row["auction_committed"]
            and row["source_kind"] == "auction_open"
        )
        if body.kind == "auction_open":
            if not ordinary or row["sale_mode"] != "auction":
                return denied("watch_committed", row)
            state, committed = "fenced", False
        elif body.kind == "first_bid":
            if not empty_auction or row["source_id"] != body.source_id:
                return denied("watch_committed", row)
            state, committed = "fenced", True
        else:
            if not (ordinary or empty_auction):
                return denied("watch_committed", row)
            state, committed = (
                ("withdrawn" if body.kind == "withdraw" else "editing"),
                True,
            )
        row = await tx.fetchrow(
            """UPDATE l08_watches SET status=$2,source_id=$3,source_kind=$4,
            auction_committed=$5,revision=revision+1 WHERE id=$1 RETURNING *""",
            body.watch_id,
            state,
            body.source_id,
            body.kind,
            committed,
        )
        await audit(
            tx,
            body.watch_id,
            "service:" + caller,
            body.kind,
            body.reason.strip() or "Guarded listing action",
            row["revision"],
        )
        await record_fact(
            tx,
            request.state.request_id,
            "commitment-changed",
            body.watch_id,
            row["revision"],
            {
                "listing_id": str(body.listing_id),
                "status": row["status"],
                "kind": body.kind,
            },
        )
        return {
            "status": "succeeded",
            "watch": watch_fact(row),
            "resource_id": str(body.watch_id),
        }

    async def retain_resolution(tx, result):
        # Local projection only, atomically retained after the real command outcome.
        # Replays reach this hook only after the exact original digest matches.
        await tx.execute(
            """INSERT INTO l13_listing_edit_bindings(operation_id,source_id,watch_id,listing_id,listing_revision,expected_revision)
            VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(operation_id) DO NOTHING""",
            UUID(result["id"]),
            body.source_id,
            body.watch_id,
            body.listing_id,
            body.listing_revision,
            body.expected_revision,
        )

    return await command(
        request.app.state.pool,
        "service:" + caller,
        idempotency_key,
        "commitment",
        body.model_dump(),
        apply,
        request_id=request.state.request_id,
        retain_result=retain_resolution
        if caller == "catalog" and body.kind == "edit"
        else None,
    )


@router.post("/internal/v2/watches/{watch_id}/edit-complete")
async def finish_edit(
    watch_id: UUID,
    body: FinishEdit,
    request: Request,
    idempotency_key: str = Header(default=""),
):
    service(request, "catalog")
    require_key(body, idempotency_key)

    async def apply(tx):
        row = await lock_watch(tx, watch_id)
        if (
            row["status"] != "editing"
            or row["source_id"] != body.source_id
            or body.listing_revision != row["listing_revision"] + 1
        ):
            return denied("edit_fence_mismatch", row)
        # Empty auctions must be re-opened against the new revision by Auction; no stale bid can slip in.
        row = await tx.fetchrow(
            """UPDATE l08_watches SET status='available',source_id=NULL,source_kind=NULL,
            listing_revision=$2,revision=revision+1 WHERE id=$1 RETURNING *""",
            watch_id,
            body.listing_revision,
        )
        await audit(
            tx,
            watch_id,
            "service:catalog",
            "edit-complete",
            "Committed listing revision",
            row["revision"],
        )
        return {"status": "succeeded", "watch": watch_fact(row)}

    return await command(
        request.app.state.pool,
        "service:catalog",
        idempotency_key,
        "edit-complete",
        {"watch_id": watch_id, **body.model_dump()},
        apply,
        request_id=request.state.request_id,
    )


@router.get("/v1/checkout-context")
async def context(listing_id: UUID, request: Request, actor=Depends(principal)):
    if "buyer" not in actor.roles or actor.actor.organization_id:
        raise AccessDenied("Use an individual buyer account")
    listing = await upstream(
        request, "catalog", f"/v1/listings/{listing_id}/publication"
    )
    row = await request.app.state.pool.fetchrow(
        "SELECT * FROM l08_watches WHERE listing_id=$1", listing_id
    )
    if (
        row is None
        or row["seller_id"] == actor.actor.subject_id
        or row["organization_id"] in actor.organizations
    ):
        raise AccessDenied("This watch cannot be purchased by this buyer")
    if (
        listing.get("id") != str(listing_id)
        or listing.get("revision") != row["listing_revision"]
    ):
        raise PublicError("listing_changed", "Reload the current watch.", status=409)
    return {"listing": listing, "watch": watch_fact(row), "simulated": True}


@router.post("/v1/exact-reservations")
async def reserve_exact(
    body: ReserveWatch,
    request: Request,
    actor=Depends(principal),
    idempotency_key: str = Header(default=""),
):
    if "buyer" not in actor.roles or actor.actor.organization_id:
        raise AccessDenied("Use an individual buyer account")
    actor_key = "user:" + str(actor.actor.subject_id)
    prior = await operation(request.app.state.pool, actor_key, idempotency_key)
    # command still checks digest on replay; no dependency needed for known outcomes.
    snapshot = listing = expires = None
    if prior is None:
        before = await request.app.state.pool.fetchrow(
            "SELECT * FROM l08_watches WHERE id=$1", body.watch_id
        )
        if before is None:
            raise PublicError("watch_unknown", "Watch not found.", status=404)
        listing = await upstream(
            request, "catalog", f"/v1/listings/{before['listing_id']}/publication"
        )
        raw = await upstream(request, "pricing", f"/v1/quotes/{body.quote_id}")
        snapshot, expires = exact_snapshot(
            raw,
            quote_id=body.quote_id,
            buyer_id=actor.actor.subject_id,
            listing_id=before["listing_id"],
            listing_revision=before["listing_revision"],
        )

    async def apply(tx):
        row = await lock_watch(tx, body.watch_id)
        if (
            row["seller_id"] == actor.actor.subject_id
            or row["organization_id"] in actor.organizations
        ):
            return denied("self_purchase", row)
        if row["status"] != "available" or row["sale_mode"] != "fixed":
            return denied("watch_committed", row)
        if (
            row["revision"] != body.expected_revision
            or row["listing_revision"] != snapshot["subject_revision"]
        ):
            return denied("stale_revision", row)
        if (
            listing.get("id") != str(row["listing_id"])
            or listing.get("physical_watch_id") != str(row["id"])
            or listing.get("revision") != row["listing_revision"]
            or listing.get("status") != "published"
        ):
            return denied("listing_changed", row)
        now = await tx.fetchval("SELECT clock_timestamp()")
        if now >= expires:
            return denied("quote_expired", row)
        order = await tx.fetchrow(
            """INSERT INTO l08_orders(id,watch_id,listing_id,buyer_id,seller_id,organization_id,
            quote_id,state,currency,total_minor,deadline,is_demo) VALUES($1,$2,$3,$4,$5,$6,$7,'awaiting_payment',$8,$9,$10,$11) RETURNING *""",
            uuid4(),
            row["id"],
            row["listing_id"],
            actor.actor.subject_id,
            row["seller_id"],
            row["organization_id"],
            body.quote_id,
            snapshot["currency"],
            snapshot["payable_minor"],
            min(expires, now + timedelta(minutes=15)),
            row["is_demo"],
        )
        await retain(
            tx, order, snapshot, row["listing_revision"], listing.get("seller_type")
        )
        await tx.execute(
            "UPDATE l08_watches SET status='reserved',source_id=$2,source_kind='fixed',seller_type=$3,revision=revision+1 WHERE id=$1",
            row["id"],
            order["id"],
            listing["seller_type"],
        )
        await audit(
            tx,
            order["id"],
            actor_key,
            "reserve",
            "Exact reviewed fixed-price reservation",
            1,
        )
        await record_fact(
            tx,
            request.state.request_id,
            "reserved",
            order["id"],
            1,
            {
                "order_id": str(order["id"]),
                "listing_id": str(row["listing_id"]),
                "buyer_id": str(order["buyer_id"]),
                "seller_id": str(row["seller_id"]),
                "state": "awaiting_payment",
            },
        )
        return {
            "status": "succeeded",
            "resource_id": str(order["id"]),
            "order": order_fact(order),
            "payment_authority": False,
        }

    return await command(
        request.app.state.pool,
        actor_key,
        idempotency_key,
        "reserve-exact",
        body.model_dump(),
        apply,
        request_id=request.state.request_id,
    )


@router.post("/internal/v2/allocations")
async def allocate(
    body: Allocate, request: Request, idempotency_key: str = Header(default="")
):
    caller = service(
        request,
        "pricing"
        if body.kind == "offer"
        else "auction"
        if body.kind in {"winner", "prebid"}
        else "orders",
    )
    require_key(body, idempotency_key)
    actor_key = "service:" + caller
    prior = await operation(request.app.state.pool, actor_key, idempotency_key)
    basis = None
    if prior is None:
        # Pricing v2 service validation binds source/buyer and immutable exact snapshot.
        basis = current_quote(
            await upstream(
                request,
                "pricing",
                f"/internal/v2/quotes/{body.quote_id}/validation?buyer_id={body.buyer_id}",
                service_auth=True,
            )
        )
        required = {
            "quote_id": str(body.quote_id),
            "buyer_id": str(body.buyer_id),
            "listing_id": str(body.listing_id),
            "listing_revision": body.listing_revision,
            "quote_revision": body.quote_revision,
            "currency": body.currency,
            "total_minor": body.total_minor,
            "source_id": str(body.source_id),
            "kind": "brand" if body.kind == "brand_job" else body.kind,
            "status": "valid",
        }
        if any(basis.get(k) != v for k, v in required.items()):
            raise PublicError(
                "quote_binding_mismatch",
                "The exact accepted allocation quote is required.",
                status=409,
            )
        retained = await upstream(
            request,
            "pricing",
            f"/internal/v2/quotes/{body.quote_id}/retained?buyer_id={body.buyer_id}",
            service_auth=True,
        )
        snapshot = retained_snapshot(retained, basis)
        listing = await upstream(
            request, "catalog", f"/v1/listings/{body.listing_id}/publication"
        )
        if (
            listing.get("id") != str(body.listing_id)
            or listing.get("physical_watch_id") != str(body.watch_id)
            or listing.get("revision") != body.listing_revision
            or listing.get("status") != "published"
        ):
            raise PublicError(
                "listing_changed", "The allocated watch source changed.", status=409
            )
        basis = {
            **basis,
            "snapshot": snapshot,
            "seller_type": listing.get("seller_type"),
        }

    async def apply(tx):
        row = await lock_watch(tx, body.watch_id)
        if (
            row["listing_id"] != body.listing_id
            or row["listing_revision"] != body.listing_revision
        ):
            return denied("listing_revision_mismatch", row)
        if row["seller_id"] == body.buyer_id:
            return denied("self_purchase", row)
        if row["revision"] != body.expected_revision:
            return denied("stale_revision", row)
        permitted = (
            row["status"] == "available"
            if body.kind in {"offer", "brand_job"}
            else (
                row["status"] == "fenced"
                and row["source_id"] == body.source_id
                and (
                    body.kind == "winner"
                    and row["auction_committed"]
                    or body.kind == "prebid"
                    and not row["auction_committed"]
                )
            )
        )
        if not permitted:
            return denied("watch_committed", row)
        now = await tx.fetchval("SELECT clock_timestamp()")
        try:
            from datetime import datetime

            expiry = datetime.fromisoformat(basis["expires_at"].replace("Z", "+00:00"))
            if now >= expiry:
                return denied("quote_expired", row)
        except (KeyError, TypeError, ValueError):
            raise PublicError(
                "pricing_unavailable",
                "Exact quote expiry cannot be verified.",
                status=503,
            ) from None
        order = await tx.fetchrow(
            """INSERT INTO l08_orders(id,watch_id,listing_id,buyer_id,seller_id,organization_id,
            quote_id,state,currency,total_minor,deadline,is_demo) VALUES($1,$2,$3,$4,$5,$6,$7,'awaiting_payment',$8,$9,$10,$11) RETURNING *""",
            uuid4(),
            body.watch_id,
            body.listing_id,
            body.buyer_id,
            row["seller_id"],
            row["organization_id"],
            body.quote_id,
            body.currency,
            body.total_minor,
            min(expiry, now + timedelta(hours=24)),
            row["is_demo"],
        )
        await retain(
            tx,
            order,
            basis["snapshot"],
            row["listing_revision"],
            basis.get("seller_type"),
        )
        await tx.execute(
            "UPDATE l08_watches SET status='reserved',source_id=$2,source_kind=$3,seller_type=$4,revision=revision+1 WHERE id=$1",
            row["id"],
            order["id"],
            body.kind,
            basis["seller_type"],
        )
        await audit(
            tx,
            order["id"],
            actor_key,
            "allocate",
            body.kind + " allocation with retained quote",
            1,
        )
        await record_fact(
            tx,
            request.state.request_id,
            "allocated",
            order["id"],
            1,
            {
                "order_id": str(order["id"]),
                "listing_id": str(row["listing_id"]),
                "buyer_id": str(order["buyer_id"]),
                "seller_id": str(row["seller_id"]),
                "state": "awaiting_payment",
                "kind": body.kind,
            },
        )
        return {
            "status": "succeeded",
            "resource_id": str(order["id"]),
            "order": order_fact(order),
        }

    return await command(
        request.app.state.pool,
        actor_key,
        idempotency_key,
        "allocate",
        body.model_dump(),
        apply,
        request_id=request.state.request_id,
    )
