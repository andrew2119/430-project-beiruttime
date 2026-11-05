from uuid import UUID
from fastapi import APIRouter, Depends, Request
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import require_scope
from service_app.orders_dependencies import principal, service
from service_app.orders_kernel import paid_fact

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
    async with request.app.state.pool.acquire() as tx:
        return await paid_fact(tx, order_id)


@router.get("/v1/orders/{order_id}/journal")
async def journal(order_id: UUID, request: Request, actor=Depends(principal)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM l08_orders WHERE id=$1", order_id)
        if row is None:
            raise PublicError("order_unknown", "Order not found.", status=404)
        readable(actor, row)
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
