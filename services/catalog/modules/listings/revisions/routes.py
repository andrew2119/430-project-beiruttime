"""Durable edit saga: source intent precedes network; no SQL lock spans HTTP."""

import json
import hashlib
from uuid import UUID, uuid5, NAMESPACE_URL
from fastapi import APIRouter, Request
from pydantic import Field
from bt_contracts.catalog.listings.v1 import SaveDraft, incomplete
from bt_contracts_core.errors import PublicError, AccessDenied
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.catalog_dependencies import (
    principal,
    seller_scope,
    assert_owner,
    service_request,
)
from service_app.listing_repository import (
    dto,
    unpack,
    digest,
    revision,
    command_key,
    check_revision,
    emit,
    lock_listing,
    require_no_pending_edit,
)

from .protocol import matches as auction_matches
from .eligibility import check_publication

router = APIRouter()


class Revise(SaveDraft):
    reason: str = Field(min_length=3, max_length=200)


def outcome(op, row):
    retained = unpack(op["result"]) if op["result"] else None
    if (
        op["status"] in ("succeeded", "denied")
        and isinstance(retained, dict)
        and retained.get("id") == str(op["id"])
    ):
        return retained
    return {
        "id": str(op["id"]),
        "status": "pending"
        if op["status"] in ("pending", "committed")
        else op["status"],
        "resource_id": str(row["id"]),
        "listing": dto(row),
    }


def confirmed(value, operation_id, row, base_revision):
    watch = value.get("watch") if isinstance(value, dict) else None
    return (
        isinstance(watch, dict)
        and value.get("status") == "succeeded"
        and watch.get("watch_id") == str(row["physical_watch_id"])
        and watch.get("listing_id") == str(row["id"])
        and watch.get("listing_revision") == base_revision
        and watch.get("status") == "editing"
        and watch.get("source_id") == str(operation_id)
    )


def public_facts_digest(facts):
    # auction-kernel/v2 hashes normalized public facts as UTF-8, including Arabic.
    return hashlib.sha256(
        json.dumps(
            facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


async def held_request(request, dependency, method, path, **kwargs):
    try:
        return await service_request(request, dependency, method, path, **kwargs)
    except (PublicError, AccessDenied):
        # A remote HTTP denial is not a retained, independently reconciled
        # command denial. In particular, source facts may already be committed.
        raise PublicError('edit_pending', 'Reconcile the retained edit; its outcome is not yet confirmed.', status=503) from None


async def finish_aborted(request, op, row, value):
    if not auction_matches(value, op, row, 'aborted'):
        raise PublicError('edit_pending', 'The prepared edit fence is awaiting confirmation.', status=503)
    async with unit_of_work(request.app.state.pool, lock_key=f"listing:{row['id']}") as tx:
        row = await lock_listing(tx, row['id'])
        op = await tx.fetchrow('SELECT * FROM catalog_listing_edits WHERE id=$1 FOR UPDATE', op['id'])
        if op['status'] in ('succeeded', 'denied'):
            return outcome(op, row)
        if (op['status'] != 'pending' or row['revision'] != op['base_revision']
                or (value['code'] == 'prepare_expired' and (op['orders_started'] or op['auction_dispatched']))):
            raise PublicError('edit_pending', 'Reconcile the retained source and physical edit fence.', status=503)
        op = await tx.fetchrow("UPDATE catalog_listing_edits SET status='denied' WHERE id=$1 RETURNING *", op['id'])
        answer = {**outcome(op, row), 'code': value['code']}
        await tx.execute('UPDATE catalog_listing_edits SET result=$2::jsonb WHERE id=$1', op['id'], json.dumps(answer))
    return answer


async def abort_review(request, op, row):
    operation_id = op["id"]
    return await held_request(
        request, "auction", "POST", f"/internal/v3/listing-edits/{operation_id}/abort",
        headers={"Idempotency-Key": str(operation_id)},
        json={"operation_id": str(operation_id), "listing_id": str(row["id"]),
              "watch_id": str(row["physical_watch_id"]),
              "listing_revision": op["base_revision"],
              "next_revision": op["base_revision"] + 1,
              "reason": "publication_review_denied"},
    )


async def resume(request, operation_id):
    person = await principal(request)
    seller_scope(person, "identity.listings.publish")
    async with request.app.state.pool.acquire() as tx:
        op = await tx.fetchrow(
            "SELECT * FROM catalog_listing_edits WHERE id=$1", operation_id
        )
        if op is None:
            raise PublicError("not_found", "Edit operation not found.", status=404)
        row = await tx.fetchrow(
            "SELECT * FROM catalog_listings WHERE id=$1", op["listing_id"]
        )
    assert_owner(row, person)
    if op["status"] in ("succeeded", "denied"):
        return outcome(op, row)
    if op['status'] == 'pending' and op['result'] and unpack(op['result']).get('status') == 'denied':
        if unpack(op['result']).get('code') == 'publication_review_denied':
            aborted = await abort_review(request, op, row)
        else:
            aborted = await held_request(request, 'auction', 'POST', f'/internal/v3/listing-edits/{operation_id}/abort')
        return await finish_aborted(request, op, row, aborted)
    if op['status'] == 'pending' and (op['orders_started'] or op['auction_prepared'] or op['auction_dispatched']):
        recovered = await held_request(request, 'auction', 'POST', f'/internal/v3/listing-edits/{operation_id}/reconcile')
        if isinstance(recovered, dict) and recovered.get('phase') == 'aborted':
            return await finish_aborted(request, op, row, recovered)
        async with request.app.state.pool.acquire() as tx:
            op = await tx.fetchrow('SELECT * FROM catalog_listing_edits WHERE id=$1', operation_id)
            row = await tx.fetchrow('SELECT * FROM catalog_listings WHERE id=$1', row['id'])
        if op['status'] in ('succeeded', 'denied'):
            return outcome(op, row)
    if op["status"] == "pending":
        proposed = {**dict(row), "facts": unpack(op["facts"])}
        try:
            await check_publication(request, proposed, str(op["id"]), person.actor.subject_id)
        except PublicError as error:
            if error.code != "publication_review_denied":
                raise
            # The remote authority must settle even an apparently unstarted
            # intent: a concurrent retry may already have prepared its fence.
            async with unit_of_work(request.app.state.pool, lock_key=f"listing:{row['id']}") as tx:
                await tx.execute(
                    "UPDATE catalog_listing_edits SET result=$2::jsonb WHERE id=$1 AND status='pending'",
                    operation_id, json.dumps({"status": "denied", "code": "publication_review_denied"}),
                )
            aborted = await abort_review(request, op, row)
            return await finish_aborted(request, op, row, aborted)
    # Orders uses stable operation keys: always retry the exact retained command.
    if op["orders_revision"] is None:
        watch = await held_request(
            request, "orders", "GET", f"/internal/v2/watches/{row['physical_watch_id']}"
        )
        if (
            not isinstance(watch, dict)
            or watch.get("listing_id") != str(row["id"])
            or watch.get("listing_revision") != op["base_revision"]
            or type(watch.get("revision")) is not int
        ):
            raise PublicError(
                "commitment_unavailable",
                "The current watch commitment cannot be confirmed.",
                status=503,
            )
        async with unit_of_work(
            request.app.state.pool, lock_key=f"listing:{row['id']}"
        ) as tx:
            await tx.execute(
                "UPDATE catalog_listing_edits SET orders_revision=$2 WHERE id=$1 AND orders_revision IS NULL",
                operation_id,
                watch["revision"],
            )
            op = await tx.fetchrow(
                "SELECT * FROM catalog_listing_edits WHERE id=$1", operation_id
            )
    if op["status"] == "pending":
        # Freeze Auction before Orders, including a listing-level hold when no
        # lot exists. Reversing this order can strand competing first-bid holds.
        try:
            auction = await service_request(
                request,
                "auction",
                "POST",
                f"/internal/v{op['auction_protocol']}/listing-edits/prepare",
                headers={"Idempotency-Key": str(operation_id)},
                json={
                    "operation_id": str(operation_id),
                    "listing_id": str(row["id"]),
                    "watch_id": str(row["physical_watch_id"]),
                    "listing_revision": op["base_revision"],
                    "next_revision": op["base_revision"] + 1,
                    "facts_digest": public_facts_digest(unpack(op["facts"])),
                    **({'orders_operation_key': str(operation_id), 'orders_expected_revision': op['orders_revision'],
                        'lease_seconds': op['auction_lease_seconds']} if op['auction_protocol'] == 3 else {}),
                },
            )
        except PublicError as error:
            if error.code != "auction_denied" or error.status != 409:
                raise
            async with unit_of_work(
                request.app.state.pool, lock_key=f"listing:{row['id']}"
            ) as tx:
                current_op = await tx.fetchrow(
                    "SELECT * FROM catalog_listing_edits WHERE id=$1 FOR UPDATE",
                    operation_id,
                )
                if current_op["status"] in ("succeeded", "denied"):
                    return outcome(current_op, row)
                if current_op["orders_started"] or current_op['auction_prepared']:
                    raise PublicError(
                        "edit_pending",
                        "Reconcile the existing physical edit fence.",
                        status=503,
                    )
                current_op = await tx.fetchrow(
                    "UPDATE catalog_listing_edits SET status='denied' WHERE id=$1 RETURNING *",
                    operation_id,
                )
                answer = {**outcome(current_op, row), "code": "auction_edit_denied"}
                await tx.execute(
                    "UPDATE catalog_listing_edits SET result=$2::jsonb WHERE id=$1",
                    operation_id,
                    json.dumps(answer),
                )
                return answer
        if not auction_matches(auction, op, row, 'prepared'):
            raise PublicError('edit_pending', 'Auction edit confirmation is pending.', status=503)
        async with unit_of_work(request.app.state.pool, lock_key=f"listing:{row['id']}") as tx:
            await tx.execute('UPDATE catalog_listing_edits SET auction_prepared=true WHERE id=$1', operation_id)
        if op['auction_protocol'] == 3:
            dispatched = await held_request(request, 'auction', 'POST', f'/internal/v3/listing-edits/{operation_id}/dispatch')
            if isinstance(dispatched, dict) and dispatched.get('phase') == 'aborted':
                return await finish_aborted(request, op, row, dispatched)
            if not auction_matches(dispatched, op, row, 'dispatched'):
                raise PublicError('edit_pending', 'Confirm the same Auction dispatch before editing.', status=503)
        async with unit_of_work(
            request.app.state.pool, lock_key=f"listing:{row['id']}"
        ) as tx:
            op = await tx.fetchrow(
                "SELECT * FROM catalog_listing_edits WHERE id=$1 FOR UPDATE",
                operation_id,
            )
            if op["status"] in ("succeeded", "denied"):
                return outcome(op, row)
            await tx.execute(
                "UPDATE catalog_listing_edits SET orders_started=true,auction_dispatched=(auction_protocol=3) WHERE id=$1",
                operation_id,
            )
        command = {
            "operation_key": str(operation_id),
            "source_id": str(operation_id),
            "watch_id": str(row["physical_watch_id"]),
            "listing_id": str(row["id"]),
            "listing_revision": op["base_revision"],
            "expected_revision": op["orders_revision"],
            "kind": "edit",
            "reason": op["reason"],
        }
        result = await held_request(
            request,
            "orders",
            "POST",
            "/internal/v2/commitments",
            headers={"Idempotency-Key": str(operation_id)},
            json=command,
        )
        if not confirmed(result, operation_id, row, op["base_revision"]):
            # Only Auction's independent authenticated Orders resolution and
            # exact terminal acknowledgement can release the prepared hold.
            if isinstance(result, dict) and result.get("status") == "denied":
                async with unit_of_work(
                    request.app.state.pool, lock_key=f"listing:{row['id']}"
                ) as tx:
                    await tx.execute(
                        "UPDATE catalog_listing_edits SET result=$2::jsonb WHERE id=$1 AND status='pending'",
                        operation_id,
                        json.dumps(result),
                    )
                aborted = await held_request(request, 'auction', 'POST', f'/internal/v3/listing-edits/{operation_id}/abort')
                return await finish_aborted(request, op, row, aborted)
            raise PublicError(
                "edit_pending",
                "The edit fence is not yet confirmed. Retry the same operation.",
                status=503,
            )
        person = await principal(request)
        seller_scope(person, "identity.listings.publish")
        async with unit_of_work(
            request.app.state.pool, lock_key=f"listing:{row['id']}"
        ) as tx:
            row = await lock_listing(tx, row["id"])
            assert_owner(row, person)
            if row["is_hidden"]:
                raise PublicError(
                    "listing_moderated",
                    "This listing cannot currently be revised.",
                    status=403,
                )
            op = await tx.fetchrow(
                "SELECT * FROM catalog_listing_edits WHERE id=$1 FOR UPDATE",
                operation_id,
            )
            if op["status"] == "pending":
                check_revision(row, op["base_revision"])
                old = unpack(row["facts"])
                row = await tx.fetchrow(
                    "UPDATE catalog_listings SET facts=$2::jsonb,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",
                    row["id"],
                    json.dumps(unpack(op["facts"])),
                )
                await tx.execute(
                    "INSERT INTO catalog_listing_history(listing_id,revision,actor_id,reason,before_facts,after_facts) VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb)",
                    row["id"],
                    row["revision"],
                    person.actor.subject_id,
                    op["reason"],
                    json.dumps(old),
                    json.dumps(unpack(op["facts"])),
                )
                await emit(tx, request, row, "revised")
                if old.get("price_minor") != unpack(row["facts"]).get("price_minor"):
                    await enqueue(
                        tx,
                        EventEnvelope(
                            type="catalog.listing.price-changed.v1",
                            source="catalog",
                            subject=str(row["id"]),
                            request_id=request.state.request_id,
                            data={
                                "listing_id": str(row["id"]),
                                "revision": row["revision"],
                            },
                        ),
                        ["communications-saved-watches"],
                    )
                await tx.execute(
                    "UPDATE catalog_listing_edits SET status='committed' WHERE id=$1",
                    operation_id,
                )
    # Commit acknowledgement is separate; a lost reply never rolls the revision back.
    finished = await held_request(
        request,
        "orders",
        "POST",
        f"/internal/v2/watches/{row['physical_watch_id']}/edit-complete",
        headers={"Idempotency-Key": str(operation_id) + ":complete"},
        json={
            "operation_key": str(operation_id) + ":complete",
            "source_id": str(operation_id),
            "listing_revision": op["base_revision"] + 1,
        },
    )
    completed_watch = finished.get("watch") if isinstance(finished, dict) else None
    if (
        not isinstance(completed_watch, dict)
        or finished.get("status") != "succeeded"
        or completed_watch.get("watch_id") != str(row["physical_watch_id"])
        or completed_watch.get("listing_id") != str(row["id"])
        or completed_watch.get("listing_revision") != op["base_revision"] + 1
        or completed_watch.get("status") not in ("available", "fenced")
    ):
        raise PublicError(
            "edit_pending",
            "The committed edit is awaiting fence reconciliation.",
            status=503,
        )
    result = await held_request(
        request,
        "auction",
        "POST",
        f"/internal/v{op['auction_protocol']}/listing-edits/{operation_id}/commit",
        headers={"Idempotency-Key": str(operation_id)},
        json={"listing_revision": op["base_revision"] + 1},
    )
    if not auction_matches(result, op, row, 'committed'):
        raise PublicError(
            "edit_pending", "Auction revision reconciliation is pending.", status=503
        )
    async with unit_of_work(
        request.app.state.pool, lock_key=f"listing:{row['id']}"
    ) as tx:
        op = await tx.fetchrow(
            "SELECT * FROM catalog_listing_edits WHERE id=$1 FOR UPDATE", operation_id
        )
        if op["status"] == "succeeded":
            return outcome(op, row)
        op = await tx.fetchrow(
            "UPDATE catalog_listing_edits SET status='succeeded' WHERE id=$1 RETURNING *",
            operation_id,
        )
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", row["id"])
        answer = outcome(op, row)
        await tx.execute(
            "UPDATE catalog_listing_edits SET result=$2::jsonb WHERE id=$1",
            operation_id,
            json.dumps(answer),
        )
    return answer


@router.post("/v1/seller/listings/{listing_id}/revisions")
@router.post("/v2/seller/listings/{listing_id}/revisions")
async def revise(listing_id: UUID, body: Revise, request: Request):
    person = await principal(request)
    seller_scope(person, "identity.listings.publish")
    expected, key = revision(request), command_key(request)
    fingerprint = digest({"revision": expected, **body.model_dump(mode="json")})
    async with request.app.state.pool.acquire() as tx:
        preview = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", listing_id)
        prior = await tx.fetchrow(
            "SELECT id FROM catalog_listing_edits WHERE listing_id=$1 AND actor_id=$2 AND operation_key=$3",
            listing_id, person.actor.subject_id, key,
        )
    assert_owner(preview, person)
    operation_id = prior["id"] if prior else uuid5(NAMESPACE_URL, f"listing-revision:{listing_id}:{person.actor.subject_id}:{key}")
    if not prior:
        check_revision(preview, expected)
        proposed = {**dict(preview), "facts": body.facts.model_dump(mode="json")}
        await check_publication(request, proposed, str(operation_id), person.actor.subject_id)
    async with unit_of_work(
        request.app.state.pool, lock_key=f"listing:{listing_id}"
    ) as tx:
        row = await lock_listing(tx, listing_id)
        assert_owner(row, person)
        op = await tx.fetchrow(
            "SELECT * FROM catalog_listing_edits WHERE listing_id=$1 AND actor_id=$2 AND operation_key=$3",
            listing_id,
            person.actor.subject_id,
            key,
        )
        if op:
            if op["digest"] != fingerprint:
                raise PublicError(
                    "idempotency_conflict", "Resume the original edit.", status=409
                )
        else:
            check_revision(row, expected)
            if row["status"] != "published" or row["is_hidden"]:
                raise PublicError(
                    "listing_frozen",
                    "This listing cannot currently be revised.",
                    status=409,
                )
            await require_no_pending_edit(tx, listing_id)
            missing = incomplete(body.facts, len(row["photo_ids"]))
            if missing:
                raise PublicError(
                    "listing_incomplete",
                    "Complete required facts.",
                    status=422,
                    details={"fields": missing},
                )
            # Sale mode changes require a new publication/auction policy, not an implicit conversion.
            if body.facts.sale_mode != unpack(row["facts"])["sale_mode"]:
                raise PublicError(
                    "sale_mode_frozen",
                    "The published sale mode cannot be changed.",
                    status=409,
                )
            op = await tx.fetchrow(
                """INSERT INTO catalog_listing_edits(id,listing_id,actor_id,organization_id,operation_key,digest,base_revision,facts,reason,auction_protocol)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,3) RETURNING *""",
                operation_id,
                listing_id,
                person.actor.subject_id,
                person.actor.organization_id,
                key,
                fingerprint,
                expected,
                body.facts.model_dump_json(),
                body.reason,
            )
    return await resume(request, op["id"])


@router.get("/v1/seller/listing-edit-operations/{operation_id}")
@router.get("/v2/seller/listing-edit-operations/{operation_id}")
async def read_operation(operation_id: UUID, request: Request):
    person = await principal(request)
    seller_scope(person)
    async with request.app.state.pool.acquire() as tx:
        op = await tx.fetchrow(
            "SELECT * FROM catalog_listing_edits WHERE id=$1", operation_id
        )
        if op is None:
            raise PublicError("not_found", "Edit operation not found.", status=404)
        row = await tx.fetchrow(
            "SELECT * FROM catalog_listings WHERE id=$1", op["listing_id"]
        )
    assert_owner(row, person)
    return outcome(op, row)


@router.post("/v1/seller/listing-edit-operations/{operation_id}/resume")
@router.post("/v2/seller/listing-edit-operations/{operation_id}/resume")
async def operation(operation_id: UUID, request: Request):
    return await resume(request, operation_id)


@router.get("/v1/seller/listings/{listing_id}/revisions")
@router.get("/v2/seller/listings/{listing_id}/revisions")
async def history(listing_id: UUID, request: Request):
    person = await principal(request)
    seller_scope(person)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow(
            "SELECT * FROM catalog_listings WHERE id=$1", listing_id
        )
        assert_owner(row, person)
        records = await tx.fetch(
            "SELECT revision,actor_id,reason,before_facts,after_facts,created_at FROM catalog_listing_history WHERE listing_id=$1 ORDER BY revision DESC LIMIT 100",
            listing_id,
        )
        pending = await tx.fetchval(
            "SELECT id FROM catalog_listing_edits WHERE listing_id=$1 AND status IN ('pending','committed')",
            listing_id,
        )
    return {
        "pending_operation_id": str(pending) if pending else None,
        "items": [
            {
                **dict(r),
                "actor_id": str(r["actor_id"]),
                "before_facts": unpack(r["before_facts"]),
                "after_facts": unpack(r["after_facts"]),
                "created_at": r["created_at"].isoformat(),
            }
            for r in records
        ],
    }
