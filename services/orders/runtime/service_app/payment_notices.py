"""One durable required payment notice intent per accepted order."""

from uuid import uuid4
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue


async def payment_notice(tx, request, order):
    event_id = await tx.fetchval(
        """INSERT INTO l13_payment_notices(order_id,event_id,buyer_id) VALUES($1,$2,$3)
        ON CONFLICT(order_id) DO NOTHING RETURNING event_id""",
        order["id"], uuid4(), order["buyer_id"],
    )
    if event_id is None:
        return
    await enqueue(tx, EventEnvelope(
        id=event_id, type="orders.payment-action-required.v3", source="orders",
        subject=str(order["id"]), request_id=request.state.request_id,
        data={"order_id": str(order["id"]), "buyer_id": str(order["buyer_id"]),
              "recipient_id": str(order["buyer_id"]), "revision": order["revision"],
              "required": True, "sample": order["is_demo"], "simulated": True},
    ), ["communications"])
