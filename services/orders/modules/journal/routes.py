from uuid import UUID
from fastapi import APIRouter, Depends, Header, Request
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import require_scope
from service_app.orders_dependencies import principal, service
from bt_contracts.orders.journal.v2 import PaidOrderFactV2

from bt_contracts.orders.journal.v3 import Movement, FinancialReadiness
from bt_contracts.orders.payments.signatures import callback_bytes
from bt_runtime.app.db import unit_of_work
from .movements import reserve, lookup, settle, current_paid_fact, financial_readiness

router = APIRouter(tags=["payment-journal-v1"])


def readable(actor, row):
    if actor.actor.organization_id is None and (
        actor.actor.subject_id == row["buyer_id"]
        or (
            row["organization_id"] is None
            and actor.actor.subject_id == row["seller_id"]
        )
    ):
        return
    if row["organization_id"] is None:
        raise AccessDenied("Order participation required")
    require_scope(actor, "orders.read", row["organization_id"])


@router.get("/internal/v1/orders/{order_id}/paid-fact")
async def paid(order_id: UUID, request: Request):
    service(
        request,
        {"trust", "communications", "eligibility", "catalog", "service-operations"},
    )
    async with unit_of_work(request.app.state.pool) as tx:
        return await current_paid_fact(tx, order_id)


@router.get("/internal/v2/orders/{order_id}/paid-fact", response_model=PaidOrderFactV2)
async def paid_v2(order_id: UUID, request: Request):
    service(request, {"trust", "communications", "eligibility", "catalog", "service-operations"})
    async with unit_of_work(request.app.state.pool) as tx:
        return await current_paid_fact(tx, order_id, version=2)


@router.get("/v1/orders/{order_id}/journal")
async def journal(order_id: UUID, request: Request, actor=Depends(principal)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order_id)
        if row is None:
            raise PublicError("order_unknown", "Order not found.", status=404)
        readable(actor, row)
        if row["currency"] != "USD":
            raise PublicError("legacy_currency_reconciliation_required", "This archived order needs recorded reconciliation.", status=409)
        group = await tx.fetchrow(
            "SELECT * FROM l13_journal_groups WHERE order_id=$1", order_id
        )
        entries = (
            await tx.fetch(
                "SELECT account,amount_minor FROM l13_journal_entries WHERE group_id=$1 ORDER BY account",
                group["id"],
            )
            if group
            else []
        )
        return {
            "simulated": True,
            "group": dict(group) if group else None,
            "entries": [dict(r) for r in entries],
            "payout_authorized": False,
        }


@router.post("/internal/v3/money-operations")
async def reserve_movement(body: Movement, request: Request):
    producer = service(request, {"trust", "service-operations"})
    reader = getattr(request.app.state, "money_policy_reader", None)
    async with unit_of_work(request.app.state.pool) as tx:
        return await reserve(tx, body, reader, request.state.request_id, producer=producer)


@router.post("/internal/v3/money-operations/lookup")
async def lookup_movement(body: Movement, request: Request):
    producer = service(request, {"trust", "service-operations"})
    reader = getattr(request.app.state, "money_policy_reader", None)
    async with unit_of_work(request.app.state.pool) as tx:
        return await lookup(tx, body, reader, producer=producer)


@router.post("/callbacks/v3/simulated-movements")
async def movement_callback(request: Request, x_bt_signature: str = Header(default="")):
    raw = await callback_bytes(request)
    async with unit_of_work(request.app.state.pool) as tx:
        return await settle(tx, raw, x_bt_signature, request.state.request_id)


@router.get("/internal/v3/orders/{order_id}/financial-readiness", response_model=FinancialReadiness)
async def readiness(order_id: UUID, request: Request):
    service(request, {"trust", "communications", "eligibility", "catalog", "service-operations"})
    async with unit_of_work(request.app.state.pool) as tx:
        return await financial_readiness(tx, order_id)
