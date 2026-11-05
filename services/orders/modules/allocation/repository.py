"""CP B-04/B-18: locks, outcome and outbox share one SQL transaction."""

import json
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from service_app.orders_kernel import command as command, audit as audit


def order_view(row):
    return {
        key: (
            (str(row[key]) if row[key] is not None else None)
            if key.endswith("_id") or key == "id"
            else row[key].isoformat()
            if key == "deadline"
            else row[key]
        )
        for key in (
            "id",
            "watch_id",
            "listing_id",
            "quote_id",
            "buyer_id",
            "seller_id",
            "organization_id",
            "state",
            "currency",
            "total_minor",
            "revision",
            "deadline",
            "is_demo",
        )
    } | {"payment_authority": False}


def watch_view(row):
    return {
        key: str(row[key]) if key.endswith("_id") else row[key]
        for key in ("listing_id", "sale_mode", "status", "revision", "is_demo")
    } | {"watch_id": str(row["id"])}


async def outcome(tx, actor_key, key):
    row = await tx.fetchrow("SELECT * FROM l08_operations WHERE actor_key=$1 AND idempotency_key=$2", actor_key, key)
    return json.loads(row["result"]) if row else None


async def event(tx, request, kind, resource_id, revision):
    await enqueue(
        tx,
        EventEnvelope(
            type="orders." + kind + ".v1",
            source="orders",
            subject=str(resource_id),
            request_id=request.state.request_id,
            data={"resource_id": str(resource_id), "revision": revision},
        ),
        ["catalog", "communications"],
    )


def denied(code):
    return {"status": "denied", "code": code, "payment_authority": False}
