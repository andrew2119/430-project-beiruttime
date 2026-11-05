"""Sole Orders aggregate adapter. Call with the caller's existing transaction.

Custody/jobs must use these guards rather than inventing order/fence algorithms.
No network, commit, release, balance or private-evidence authority lives here.
"""

import hashlib
import json
from uuid import UUID, uuid4
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def watch_fact(row):
    return {
        k: str(row[k]) if isinstance(row[k], UUID) else row[k]
        for k in (
            "listing_id",
            "seller_id",
            "organization_id",
            "listing_revision",
            "seller_type",
            "sale_mode",
            "status",
            "revision",
            "source_id",
            "source_kind",
            "auction_committed",
            "is_demo",
        )
    } | {"watch_id": str(row["id"])}


def order_fact(row):
    names = (
        "id",
        "watch_id",
        "listing_id",
        "buyer_id",
        "seller_id",
        "organization_id",
        "quote_id",
        "state",
        "currency",
        "total_minor",
        "revision",
        "deadline",
        "is_demo",
    )
    return {
        k: str(row[k]) if isinstance(row[k], UUID) else row[k].isoformat() if k == "deadline" else row[k] for k in names
    } | {"payment_authority": False}


async def lock_watch(tx, watch_id):
    # Also serializes future registration: use the existing physical-watch key.
    await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "l08-watch:" + str(watch_id))
    row = await tx.fetchrow("SELECT * FROM l08_watches WHERE id=$1 FOR UPDATE", watch_id)
    if row is None:
        raise PublicError("watch_unknown", "The watch is not registered.", status=404)
    return row


async def lock_order(tx, order_id, expected_revision=None, require_paid=False):
    row = await tx.fetchrow("SELECT * FROM l08_orders WHERE id=$1 FOR UPDATE", order_id)
    if row is None:
        raise PublicError("order_unknown", "Order not found.", status=404)
    if expected_revision is not None and row["revision"] != expected_revision:
        raise PublicError("stale_revision", "Reload the current order.", status=409)
    if require_paid and row["state"] != "paid_held":
        raise PublicError("payment_required", "Confirmed simulated held payment is required.", status=409)
    return row


async def transition_order(tx, order_id, expected_revision, allowed_states, state):
    # S2 does not authorize payout/release/refund/completion. Those require a new policy.
    if state not in {"payment_unknown", "expired_fenced", "paid_held"}:
        raise PublicError("transition_unreleased", "This transition is not available.", status=409)
    if state == "paid_held":
        raise PublicError("payment_authority_required", "Only the signed payment journal may mark paid.", status=403)
    row = await lock_order(tx, order_id, expected_revision)
    if row["state"] not in allowed_states or row["state"] == "paid_held":
        raise PublicError("transition_denied", "The current order cannot make this transition.", status=409)
    return await tx.fetchrow(
        "UPDATE l08_orders SET state=$2,revision=revision+1 WHERE id=$1 RETURNING *", order_id, state
    )


async def paid_fact(tx, order_id):
    row = await tx.fetchrow(
        """SELECT o.*,q.quote_revision,q.listing_revision,q.seller_type,
        j.id AS journal_group_id FROM l08_orders o
        LEFT JOIN l13_order_quotes q ON q.order_id=o.id
        LEFT JOIN l13_journal_groups j ON j.order_id=o.id WHERE o.id=$1""",
        order_id,
    )
    if row is None:
        raise PublicError("order_unknown", "Order not found.", status=404)
    return (
        order_fact(row)
        | {
            k: str(row[k]) if isinstance(row[k], UUID) else row[k]
            for k in ("quote_revision", "listing_revision", "seller_type", "journal_group_id")
        }
        | {
            "order_id": str(row["id"]),
            "paid": row["state"] == "paid_held" and row["journal_group_id"] is not None,
            "simulated": True,
            "payout_authorized": False,
        }
    )


async def audit(tx, resource_id, actor_key, action, reason, revision):
    await tx.execute(
        "INSERT INTO l08_audit(resource_id,actor_key,action,reason,revision) VALUES($1,$2,$3,$4,$5)",
        resource_id,
        actor_key,
        action,
        reason,
        revision,
    )


async def record_fact(tx, request_id, kind, resource_id, revision, data):
    # Durable destination stays pending until its versioned subscriber is enabled.
    await enqueue(
        tx,
        EventEnvelope(
            type="orders." + kind + ".v1",
            source="orders",
            subject=str(resource_id),
            request_id=request_id,
            data={"resource_id": str(resource_id), "revision": revision, **data},
        ),
        ["communications-order-timeline"],
    )


async def operation(pool, actor_key, key):
    row = await pool.fetchrow(
        "SELECT result FROM l08_operations WHERE actor_key=$1 AND idempotency_key=$2", actor_key, key
    )
    return decoded(row["result"]) if row else None


async def command(pool, actor_key, key, action, payload, handler, *, request_id, retain_result=None):
    if not key or len(key) > 100 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise PublicError("idempotency_required", "Provide one stable Idempotency-Key.", status=422)
    digest = hashlib.sha256(
        json.dumps({"action": action, "body": payload}, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    async with unit_of_work(pool, lock_key="l08-op:" + actor_key + ":" + key) as tx:
        prior = await tx.fetchrow(
            "SELECT * FROM l08_operations WHERE actor_key=$1 AND idempotency_key=$2", actor_key, key
        )
        if prior:
            if prior["digest"] != digest:
                raise PublicError("idempotency_conflict", "This operation key has different content.", status=409)
            result = decoded(prior["result"])
            # Optional local receipt projection shares this transaction. A legacy
            # replay is eligible only AFTER its exact original digest matches.
            if retain_result is not None:
                await retain_result(tx, result)
            return result
        result = {"id": str(uuid4()), "request_id": request_id, **await handler(tx)}
        await tx.execute(
            "INSERT INTO l08_operations(id,actor_key,idempotency_key,digest,result) VALUES($1,$2,$3,$4,$5::jsonb)",
            UUID(result["id"]),
            actor_key,
            key,
            digest,
            json.dumps(result, default=str),
        )
        if retain_result is not None:
            await retain_result(tx, result)
        return result
