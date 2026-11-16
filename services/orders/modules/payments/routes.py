from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, Request
from bt_contracts.orders.payments import StartPayment, SelectPaymentMethod, Simulate, PaymentCallback
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from service_app.orders_dependencies import principal
from service_app.orders_kernel import command, lock_order, order_fact, decoded, audit
from .processor import project, verify, sign, secret, process
from service_app.payment_clock import can_initiate, initiated_until, deadline_for

router = APIRouter(tags=["simulated-payments-v1"])


def owner(actor, order):
    if (
        actor.actor.organization_id is not None
        or actor.actor.subject_id != order["buyer_id"]
        or "buyer" not in actor.roles
    ):
        raise AccessDenied("Only the current individual buyer may pay")


@router.get("/v1/orders/{order_id}/checkout")
async def checkout(order_id: UUID, request: Request, actor=Depends(principal)):
    async with request.app.state.pool.acquire() as tx:
        order = await tx.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order_id)
        if order is None:
            raise PublicError("order_unknown", "Order not found.", status=404)
        owner(actor, order)
        quote = await tx.fetchrow(
            "SELECT * FROM l13_order_quotes WHERE order_id=$1", order_id
        )
        attempts = await tx.fetch(
            "SELECT * FROM l13_payment_attempts WHERE order_id=$1 ORDER BY created_at DESC,id DESC LIMIT 20",
            order_id,
        )
        now = await tx.fetchval("SELECT clock_timestamp()")
        return {
            "order": order_fact(order),
            "quote": decoded(quote["snapshot"]) if quote else None,
            "attempts": [project(a) for a in attempts],
            "simulated": True,
            "payable": quote is not None
            and (
                order["state"] == "awaiting_payment"
                or (
                    order["state"] == "payment_unknown"
                    and bool(attempts)
                    and attempts[0]["state"] == "declined"
                )
            )
            and order["currency"] == "USD"
            and order.get("deadline") is not None
            and now < order["deadline"]
            and not any(
                attempt["state"] in {"pending", "confirmed", "held"}
                for attempt in attempts
            ),
            "server_time": now.isoformat(),
            "requires_current_quote": quote is None,
        }


@router.post("/v1/orders/{order_id}/payment-method")
async def select_method(
    order_id: UUID, body: SelectPaymentMethod, request: Request,
    actor=Depends(principal), idempotency_key: str = Header(default=""),
):
    async def apply(tx):
        order = await lock_order(tx, order_id)
        owner(actor, order)
        if order["revision"] != body.expected_revision:
            return {"status": "denied", "code": "stale_revision"}
        if order["state"] not in {"awaiting_payment", "payment_unknown"} or not order["notified_at"]:
            return {"status": "denied", "code": "order_not_payable"}
        now = await tx.fetchval("SELECT clock_timestamp()")
        if order["deadline"] is None or now >= order["deadline"]:
            return {"status": "denied", "code": "deadline_elapsed"}
        if await tx.fetchval("SELECT 1 FROM l13_payment_attempts WHERE order_id=$1 AND state<>'declined'", order_id):
            return {"status": "denied", "code": "reconciliation_required"}
        # Selection can shorten the remaining window, never move its start time.
        order = await tx.fetchrow(
            "UPDATE l08_orders SET payment_method=$2,deadline=$3,revision=revision+1 WHERE id=$1 RETURNING *",
            order_id, body.route, deadline_for(order["notified_at"], body.route, order["initiation_extended_until"]),
        )
        return {"status": "succeeded", "order": order_fact(order)}
    return await command(request.app.state.pool, "user:" + str(actor.actor.subject_id), idempotency_key,
                         "payment-method", {"order_id": order_id, **body.model_dump()}, apply, request_id=request.state.request_id)


@router.post("/v1/orders/{order_id}/payment-attempts")
async def start(
    order_id: UUID,
    body: StartPayment,
    request: Request,
    actor=Depends(principal),
    idempotency_key: str = Header(default=""),
):
    secret()  # Missing configuration must fail closed before producing any attempt.
    current = await request.app.state.pool.fetchrow(
        "SELECT * FROM l08_orders WHERE id=$1", order_id
    )
    if current is None:
        raise PublicError("order_unknown", "Order not found.", status=404)
    owner(actor, current)

    async def apply(tx):
        order = await lock_order(tx, order_id)
        owner(actor, order)
        existing = await tx.fetchrow(
            "SELECT * FROM l13_payment_attempts WHERE order_id=$1 AND state IN ('pending','confirmed','held')",
            order_id,
        )
        if existing:
            return {
                "status": "succeeded",
                "attempt": project(existing),
                "paid": order["state"] == "paid_held",
            }
        if order["revision"] != body.expected_revision:
            return {"status": "denied", "code": "stale_revision"}
        if order["state"] not in {"awaiting_payment", "payment_unknown"}:
            return {"status": "denied", "code": "order_not_payable"}
        latest = await tx.fetchrow(
            "SELECT state FROM l13_payment_attempts WHERE order_id=$1 ORDER BY created_at DESC,id DESC LIMIT 1",
            order_id,
        )
        if order["state"] == "payment_unknown" and (
            not latest or latest["state"] != "declined"
        ):
            return {"status": "denied", "code": "reconciliation_required"}
        quote = await tx.fetchrow(
            "SELECT * FROM l13_order_quotes WHERE order_id=$1", order_id
        )
        if quote is None:
            return {"status": "denied", "code": "retained_quote_required"}
        provided = any(
            value is not None
            for value in (body.quote_revision, body.total_minor, body.currency)
        )
        matches = (
            body.quote_revision == quote["quote_revision"]
            and body.total_minor == order["total_minor"]
            and body.currency == order["currency"]
        )
        if (provided and not matches) or (
            not provided and not decoded(quote["snapshot"]).get("reviewed_at")
        ):
            return {"status": "denied", "code": "exact_quote_review_required"}
        now = await tx.fetchval("SELECT clock_timestamp()")
        if not can_initiate(order, body.route, now):
            return {"status": "denied", "code": "deadline_elapsed"}
        extension = initiated_until(order, body.route, now)
        attempt_id = uuid4()
        attempt = await tx.fetchrow(
            """INSERT INTO l13_payment_attempts(id,order_id,buyer_id,quote_id,quote_revision,currency,total_minor,route,reference)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
            attempt_id,
            order_id,
            order["buyer_id"],
            order["quote_id"],
            quote["quote_revision"],
            order["currency"],
            order["total_minor"],
            body.route,
            "SIM-" + str(attempt_id),
        )
        await tx.execute(
            """UPDATE l08_orders SET state='payment_unknown',revision=revision+1,payment_method=$2,
            initiation_extended_until=$3,deadline=$4 WHERE id=$1""",
            order_id, body.route, extension, deadline_for(order["notified_at"], body.route, extension),
        )
        await audit(
            tx,
            order_id,
            "user:" + str(actor.actor.subject_id),
            "payment-attempt",
            "Simulated " + body.route + " attempt retained",
            order["revision"] + 1,
        )
        return {"status": "succeeded", "attempt": project(attempt), "paid": False}

    return await command(
        request.app.state.pool,
        "user:" + str(actor.actor.subject_id),
        idempotency_key,
        "payment-start",
        {"order_id": order_id, **body.model_dump(exclude_none=True)},
        apply,
        request_id=request.state.request_id,
    )


@router.post("/callbacks/v1/simulated")
async def callback(request: Request, x_bt_signature: str = Header(default="")):
    raw = await request.body()
    body = verify(raw, x_bt_signature)
    async with unit_of_work(request.app.state.pool) as tx:
        return await process(tx, body, request.state.request_id)


@router.post("/v1/payment-attempts/{attempt_id}/simulate")
async def simulate(
    attempt_id: UUID,
    body: Simulate,
    request: Request,
    actor=Depends(principal),
    idempotency_key: str = Header(default=""),
):
    current = await request.app.state.pool.fetchrow(
        """SELECT o.* FROM l08_orders o JOIN l13_payment_attempts a ON a.order_id=o.id WHERE a.id=$1""",
        attempt_id,
    )
    if current is None:
        raise PublicError("attempt_unknown", "Payment attempt not found.", status=404)
    owner(actor, current)

    async def apply(tx):
        # Same lock order as callback/start. No separate simulator success algorithm.
        order = await lock_order(tx, current["id"])
        owner(actor, order)
        attempt = await tx.fetchrow(
            "SELECT * FROM l13_payment_attempts WHERE id=$1", attempt_id
        )
        callback = PaymentCallback(
            event_id=uuid4(),
            attempt_id=attempt_id,
            **{
                k: attempt[k]
                for k in (
                    "order_id",
                    "buyer_id",
                    "quote_id",
                    "quote_revision",
                    "currency",
                    "total_minor",
                    "route",
                    "reference",
                )
            },
            outcome=body.outcome,
            sequence=attempt["sequence"] + 1,
        )
        raw = callback.model_dump_json().encode()
        verified = verify(raw, sign(raw))
        return await process(tx, verified, request.state.request_id)

    return await command(
        request.app.state.pool,
        "user:" + str(actor.actor.subject_id),
        idempotency_key,
        "simulate",
        {"attempt_id": attempt_id, **body.model_dump()},
        apply,
        request_id=request.state.request_id,
    )
