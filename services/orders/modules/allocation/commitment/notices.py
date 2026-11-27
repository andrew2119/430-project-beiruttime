"""Clock starts only on an exact authenticated durable inbox receipt."""

from fastapi import APIRouter, Request
from bt_contracts.orders.allocation.v3 import PaymentNoticeReceipt, notice_matches
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from service_app.orders_dependencies import service
from service_app.orders_kernel import lock_order, order_fact, audit, record_fact
from service_app.payment_clock import deadline_for

router = APIRouter(tags=["notified-payment-v3"])


@router.post("/internal/v3/payment-notices")
async def received(body: PaymentNoticeReceipt, request: Request):
    service(request, "communications")
    async with unit_of_work(request.app.state.pool) as tx:
        order = await lock_order(tx, body.order_id)
        intent = await tx.fetchrow("SELECT * FROM l13_payment_notices WHERE order_id=$1 FOR UPDATE", body.order_id)
        now = await tx.fetchval("SELECT clock_timestamp()")
        if intent is None or not notice_matches(body, intent, order, now):
            raise PublicError("notice_binding_mismatch", "The original buyer payment notice is required.", status=409)
        if intent["notified_at"] is not None:
            if intent["notice_id"] != body.notice_id or intent["notified_at"] != body.notified_at:
                raise PublicError("notice_conflict", "The original notice cannot be replaced.", status=409)
            return {"status": "succeeded", "order": order_fact(order)}
        if order["state"] != "awaiting_notification" or order["currency"] != "USD":
            raise PublicError("notice_reconciliation_required", "The order needs recorded reconciliation.", status=409)
        await tx.execute(
            """UPDATE l13_payment_notices SET notice_id=$2,notified_at=$3,verified_delivery_recorded=true
            WHERE order_id=$1""", order["id"], body.notice_id, body.notified_at,
        )
        order = await tx.fetchrow(
            """UPDATE l08_orders SET notified_at=$2,deadline=$3,state='awaiting_payment',revision=revision+1
            WHERE id=$1 RETURNING *""", order["id"], body.notified_at, deadline_for(body.notified_at),
        )
        await audit(tx, order["id"], "service:communications", "payment-notified", "Required buyer notice durably available", order["revision"])
        await record_fact(tx, request.state.request_id, "payment-notified", order["id"], order["revision"], {"notified_at": body.notified_at.isoformat(), "deadline": order["deadline"].isoformat()})
        return {"status": "succeeded", "order": order_fact(order)}
