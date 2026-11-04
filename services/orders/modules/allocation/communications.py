"""Released Communications V1 reservation intent, never payment authority."""

from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue


class InboxDestination:
    def __init__(self, dependency):
        self.dependency = dependency

    async def request(self, method, path, **options):
        if method != "POST" or path != "/internal/v1/events":
            raise ValueError("Only the fixed outbox receiver path may be adapted")
        return await self.dependency.request(method, "/internal/v1/inbox/events", **options)


async def reservation_notice(tx, request, order):
    event = EventEnvelope(
        type="orders.reservation-created.v1",
        source="orders",
        subject=str(order["id"]),
        request_id=request.state.request_id,
        time=order["created_at"],
        data={
            "occurrence_id": "reservation:" + str(order["id"]),
            "recipient_id": str(order["buyer_id"]),
            "kind": "reservation_ready",
            "resource_id": str(order["id"]),
            "resource_revision": order["revision"],
            "resource_owner_id": str(order["buyer_id"]),
            "event_time": order["created_at"].isoformat(),
            "required": True,
            "sample": order["is_demo"],
        },
    )
    await enqueue(tx, event, ["communications"])
