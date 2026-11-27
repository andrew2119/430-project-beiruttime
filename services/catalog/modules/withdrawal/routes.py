import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Request
from bt_contracts.catalog.withdrawal import Withdraw
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.catalog_dependencies import (
    principal,
    seller_scope,
    assert_owner,
    service_request,
)

router = APIRouter(tags=["listing-withdrawal-v1"])


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


def view(row):
    return {
        k: str(row[k]) if isinstance(row[k], UUID) else row[k]
        for k in (
            "id",
            "listing_id",
            "base_revision",
            "state",
            "operation_key",
            "reason",
        )
    } | {
        "status": row["state"],
        "outcome": unpack(row["outcome"]) if row["outcome"] else None,
        "next_action": "retry_same_operation"
        if row["state"] == "pending"
        else "exception_route"
        if row["state"] == "denied"
        else "none",
    }


def command_headers(request):
    key = request.headers.get("Idempotency-Key", "")
    if (
        not key
        or len(key) > 100
        or not all(c.isascii() and (c.isalnum() or c in "-_:.") for c in key)
    ):
        raise PublicError(
            "idempotency_required", "Use one stable operation key.", status=422
        )
    try:
        revision = int(request.headers.get("If-Match", "").strip('"'))
        if revision < 1:
            raise ValueError()
    except ValueError:
        raise PublicError(
            "revision_required", "Supply the current listing revision.", status=428
        ) from None
    return key, revision


async def source_locked(tx, listing_id):
    try:
        from service_app.listing_repository import lock_listing, require_no_pending_edit
    except ImportError:
        raise PublicError(
            "catalog_unavailable",
            "The current listing mutation authority is unavailable.",
            status=503,
        ) from None
    row = await lock_listing(tx, listing_id)
    await require_no_pending_edit(tx, listing_id)
    return row


async def owned(request, listing_id):
    person = await principal(request)
    seller_scope(person, "identity.listings.publish")
    row = await request.app.state.pool.fetchrow(
        "SELECT * FROM catalog_listings WHERE id=$1", listing_id
    )
    assert_owner(row, person)
    return person, row


@router.get("/v1/me/withdrawals")
async def mine(request: Request):
    person = await principal(request)
    seller_scope(person, "identity.listings.publish")
    rows = await request.app.state.pool.fetch(
        """SELECT w.* FROM l13_listing_withdrawals w JOIN catalog_listings l ON l.id=w.listing_id
        WHERE ($2::uuid IS NULL AND l.organization_id IS NULL AND l.owner_subject_id=$1) OR l.organization_id=$2
        ORDER BY w.created_at DESC,w.id LIMIT 100""",
        person.actor.subject_id,
        person.actor.organization_id,
    )
    return {"items": [view(row) for row in rows]}


@router.get("/v1/listings/{listing_id}/withdrawals/current")
async def current(listing_id: UUID, request: Request):
    await owned(request, listing_id)
    intent = await request.app.state.pool.fetchrow(
        "SELECT * FROM l13_listing_withdrawals WHERE listing_id=$1", listing_id
    )
    return view(intent) if intent else {"status": "none", "listing_id": str(listing_id)}


@router.post("/v1/listings/{listing_id}/withdrawals")
async def withdraw(listing_id: UUID, body: Withdraw, request: Request):
    person, _ = await owned(request, listing_id)
    key, expected = command_headers(request)
    async with unit_of_work(
        request.app.state.pool, lock_key=f"listing:{listing_id}"
    ) as tx:
        row = await source_locked(tx, listing_id)
        assert_owner(row, person)
        await tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            "l13-withdraw-op:" + str(person.actor.subject_id) + ":" + key,
        )
        prior_key = await tx.fetchrow(
            "SELECT listing_id FROM l13_listing_withdrawals WHERE actor_id=$1 AND operation_key=$2",
            person.actor.subject_id,
            key,
        )
        if prior_key and prior_key["listing_id"] != listing_id:
            raise PublicError(
                "idempotency_conflict",
                "This withdrawal key belongs to another listing.",
                status=409,
            )
        intent = await tx.fetchrow(
            "SELECT * FROM l13_listing_withdrawals WHERE listing_id=$1", listing_id
        )
        if intent:
            if (
                intent["actor_id"] != person.actor.subject_id
                or intent["organization_id"] != person.actor.organization_id
                or intent["operation_key"] != key
                or intent["base_revision"] != expected
                or intent["reason"] != body.reason
            ):
                raise PublicError(
                    "withdrawal_in_progress",
                    "Resume the original withdrawal operation.",
                    status=409,
                )
            if intent["state"] != "pending":
                return view(intent)
        else:
            if row["revision"] != expected:
                raise PublicError(
                    "stale_revision",
                    "Reload the current listing before withdrawing.",
                    status=409,
                )
            if row["status"] != "published":
                raise PublicError(
                    "listing_not_available",
                    "Only a published available listing may be withdrawn.",
                    status=409,
                )
            intent = await tx.fetchrow(
                """INSERT INTO l13_listing_withdrawals(id,listing_id,actor_id,organization_id,operation_key,base_revision,reason)
                VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
                uuid4(),
                listing_id,
                person.actor.subject_id,
                person.actor.organization_id,
                key,
                expected,
                body.reason,
            )
            await tx.execute(
                "UPDATE catalog_listings SET status='withdrawal_pending',updated_at=clock_timestamp() WHERE id=$1",
                listing_id,
            )
            await tx.execute(
                """INSERT INTO l13_withdrawal_audit(listing_id,actor_id,organization_id,reason,state,listing_revision)
                VALUES($1,$2,$3,$4,'pending',$5)""",
                listing_id,
                person.actor.subject_id,
                person.actor.organization_id,
                body.reason,
                expected,
            )
    # The locally unavailable projection precedes ALL remote work. No SQL lock spans HTTP.
    remote_key = "withdraw:" + str(intent["id"])
    payload = unpack(intent["remote_payload"]) if intent["remote_payload"] else None
    try:
        if payload is None:
            watch = await service_request(
                request,
                "orders",
                "GET",
                f"/internal/v2/watches/{row['physical_watch_id']}",
            )
            if (
                watch.get("watch_id") != str(row["physical_watch_id"])
                or watch.get("listing_id") != str(listing_id)
                or watch.get("listing_revision") != expected
                or type(watch.get("revision")) is not int
            ):
                raise PublicError(
                    "orders_unavailable",
                    "The current commitment cannot be verified.",
                    status=503,
                )
            proposed = {
                "operation_key": remote_key,
                "watch_id": str(row["physical_watch_id"]),
                "listing_id": str(listing_id),
                "listing_revision": expected,
                "expected_revision": watch["revision"],
                "source_id": str(intent["id"]),
                "kind": "withdraw",
                "reason": body.reason,
            }
            async with unit_of_work(
                request.app.state.pool, lock_key=f"listing:{listing_id}"
            ) as tx:
                fresh = await tx.fetchrow(
                    "SELECT * FROM l13_listing_withdrawals WHERE id=$1 FOR UPDATE",
                    intent["id"],
                )
                if fresh["remote_payload"]:
                    payload = unpack(fresh["remote_payload"])
                else:
                    await tx.execute(
                        "UPDATE l13_listing_withdrawals SET remote_payload=$2::jsonb WHERE id=$1",
                        intent["id"],
                        json.dumps(proposed),
                    )
                    payload = proposed
        answer = await service_request(
            request,
            "orders",
            "POST",
            "/internal/v2/commitments",
            headers={"Idempotency-Key": remote_key},
            json=payload,
        )
    except PublicError:
        # HTTP failure is not a durable command denial. Freeze and replay original payload.
        return view(intent) | {"status": "pending", "code": "commitment_unavailable"}
    status = answer.get("status")
    if status not in {"succeeded", "denied"}:
        return view(intent) | {"status": "pending", "code": "commitment_unavailable"}
    proof = answer.get("watch", {})
    if status == "succeeded" and (
        proof.get("watch_id") != payload["watch_id"]
        or proof.get("listing_id") != str(listing_id)
        or proof.get("status") != "withdrawn"
        or proof.get("source_id") != str(intent["id"])
    ):
        return view(intent) | {"status": "pending", "code": "commitment_unavailable"}
    # Revalidate current business membership after the network gap, before projecting final state.
    person, _ = await owned(request, listing_id)
    async with unit_of_work(
        request.app.state.pool, lock_key=f"listing:{listing_id}"
    ) as tx:
        row = await source_locked(tx, listing_id)
        assert_owner(row, person)
        intent = await tx.fetchrow(
            "SELECT * FROM l13_listing_withdrawals WHERE listing_id=$1 FOR UPDATE",
            listing_id,
        )
        if intent["state"] != "pending":
            return view(intent)
        if row["revision"] != expected or row["status"] != "withdrawal_pending":
            raise PublicError(
                "withdrawal_held",
                "Listing changed; the physical commitment remains held.",
                status=409,
            )
        state = "withdrawn" if status == "succeeded" else "published"
        revision = expected + int(status == "succeeded")
        await tx.execute(
            "UPDATE catalog_listings SET status=$2,revision=$3,updated_at=clock_timestamp() WHERE id=$1",
            listing_id,
            state,
            revision,
        )
        intent = await tx.fetchrow(
            "UPDATE l13_listing_withdrawals SET state=$2,outcome=$3::jsonb,updated_at=clock_timestamp() WHERE listing_id=$1 RETURNING *",
            listing_id,
            status,
            json.dumps(
                {
                    "code": answer.get("code"),
                    "exception_route": (
                        "/seller/auctions"
                        if proof.get("status") == "fenced"
                        else "/checkout"
                    )
                    if status == "denied"
                    else None,
                }
            ),
        )
        await tx.execute(
            """INSERT INTO l13_withdrawal_audit(listing_id,actor_id,organization_id,reason,state,listing_revision)
            VALUES($1,$2,$3,$4,$5,$6)""",
            listing_id,
            person.actor.subject_id,
            person.actor.organization_id,
            body.reason,
            state,
            revision,
        )
        if status == "succeeded":
            await enqueue(
                tx,
                EventEnvelope(
                    type="catalog.listing.withdrawn.v1",
                    source="catalog",
                    subject=str(listing_id),
                    request_id=request.state.request_id,
                    data={
                        "listing_id": str(listing_id),
                        "revision": revision,
                        "status": "withdrawn",
                        "seller_id": str(row["owner_subject_id"]),
                        "organization_id": str(row["organization_id"])
                        if row["organization_id"]
                        else None,
                        "is_demo": row["is_demo"],
                    },
                ),
                ["communications-listing-withdrawals"],
            )
        return view(intent)
