"""The kernel serializes final price/leader/end; this module owns only durable close intent."""

import hashlib
import json
from uuid import UUID, uuid4
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.kernel import lock_lot, server_now, transition
from .support_events import retain_support


def public(row, currency=None, *, version=1):
    if version == 1 and row["state"] == "ended_legacy_review":
        raise PublicError("contract_upgrade_required", "Use the fixed-end result contract.", status=409)
    return {
        "auction_id": str(row["auction_id"]),
        "end_version": row["end_version"],
        "close_version": row["close_version"],
        "status": row["state"],
        "reason": row["reason"],
        "winner": "Bidder "
        + hashlib.sha256(
            f"{row['auction_id']}:{row['winner_id']}".encode()
        ).hexdigest()[:8]
        if row["winner_id"]
        else None,
        "closing_minor": row["closing_minor"] if (currency or row.get("currency")) == "USD" else None,
        "currency": "USD" if (currency or row.get("currency")) == "USD" else None,
        "order_available": row["order_id"] is not None,
    }


def recovery(row, currency):
    value = public(row, currency, version=2)
    state = row["state"]
    legacy = state == "ended_legacy_review"
    pending = state == "allocation_pending"
    return value | {
        "schema_version": 3,
        "operation_id": str(row["id"]),
        "assignment_required": (legacy or pending or state == "allocation_denied") and not row.get("responsible_operator_id"),
        "revision": row["result_revision"],
        "allocation_operation": "close:" + str(row["auction_id"]) if row["winner_id"] else None,
        "pending_reason": "legacy_reconciliation" if legacy else "allocation_reconciliation" if pending else None,
        "next_actor": "operator" if legacy or state == "allocation_denied" else "auction" if pending else None,
        "next_review_at": row.get("response_due_at") if legacy or pending or state == "allocation_denied" else None,
        **{key: row.get(key) for key in ("responsible_operator_id", "next_action", "response_due_at", "escalation_due_at", "escalated_at")},
    }


async def bind_follow_up(tx, app, row):
    if row["state"] not in {"allocation_pending", "allocation_denied", "ended_legacy_review"}:
        return row
    if row.get("responsible_operator_id"):
        return row
    try:
        operator = UUID(str(getattr(app.state, "closing_operator_id", "")))
        if operator.int == 0:
            raise ValueError()
    except ValueError:
        operator = None
    action = {"allocation_pending": "reconcile_allocation", "allocation_denied": "review_allocation_denial",
              "ended_legacy_review": "reconcile_legacy_purchase"}[row["state"]]
    return await tx.fetchrow(
        """UPDATE l13_auction_closes SET responsible_operator_id=$2,next_action=$3,
        response_due_at=COALESCE(response_due_at,created_at+interval '24 hours'),
        escalation_due_at=COALESCE(escalation_due_at,created_at+interval '48 hours')
        WHERE auction_id=$1 AND responsible_operator_id IS NULL RETURNING *""",
        row["auction_id"], operator, action,
    ) or row


async def recover_assignments(app):
    async with unit_of_work(app.state.pool) as tx:
        rows = await tx.fetch(
            """SELECT * FROM l13_auction_closes
            WHERE responsible_operator_id IS NULL
            AND state IN ('allocation_pending','allocation_denied','ended_legacy_review')
            ORDER BY created_at,auction_id LIMIT 10 FOR UPDATE SKIP LOCKED"""
        )
        for row in rows:
            await bind_follow_up(tx, app, row)


async def close(app, auction_id, expected_end_version, request_id):
    async with unit_of_work(app.state.pool) as tx:
        lot = await lock_lot(tx, auction_id)
        prior = await tx.fetchrow(
            "SELECT * FROM l13_auction_closes WHERE auction_id=$1 FOR UPDATE", auction_id
        )
        if prior:
            prior = await bind_follow_up(tx, app, prior)
            return public(prior, lot["currency"], version=2)
        if lot["end_version"] != expected_end_version:
            raise PublicError(
                "stale_end_version",
                "The auction end changed; discard the old close job.",
                status=409,
            )
        now = await server_now(tx)
        scheduled_end = lot.get("scheduled_ends_at")
        if scheduled_end is None:
            raise PublicError("kernel_upgrade_required", "The fixed scheduled end is unavailable.", status=503)
        if now < scheduled_end:
            raise PublicError(
                "auction_not_ended",
                "The current authoritative end has not passed.",
                status=409,
            )
        if lot["mode"] in {"prebid_pending", "prebid_reserved"} or lot["currency"] != "USD":
            # Ending is temporal; it does not decide legacy money or release a
            # canonical financial mode. Its owner must reconcile the old intent.
            row = await tx.fetchrow(
                """INSERT INTO l13_auction_closes(auction_id,id,end_version,close_version,winner_id,closing_minor,state,reason,quote_request,scheduled_ends_at)
                VALUES($1,$2,$3,$4,NULL,$5,'ended_legacy_review',$6,NULL,$7) RETURNING *""",
                auction_id, uuid4(), lot["end_version"], lot["close_version"], lot["current_minor"],
                "legacy_currency" if lot["currency"] != "USD" else "legacy_purchase_outcome_under_review", scheduled_end,
            )
            row = await bind_follow_up(tx, app, row)
            await enqueue(tx, EventEnvelope(
                type="auction.ended-legacy-review.v2", source="auction", subject=str(auction_id), request_id=request_id,
                data={"auction_id": str(auction_id), "listing_id": str(lot["listing_id"]),
                      "end_version": lot["end_version"], "scheduled_ends_at": scheduled_end.isoformat(),
                      "outcome": "ended_legacy_review", "financial_hold_retained": True,
                      "automatic_runner_up": False, "automatic_resume": False,
                      "next_action": "legacy_operation_reconciliation", "follow_up_hours": 24},
            ), ["communications-auction-results"])
            return public(row, lot["currency"], version=2)
        if lot["mode"] != "bidding":
            raise PublicError(
                "auction_committed", "A competing auction mode is held.", status=409
            )
        reason = (
            "no_bids"
            if lot["accepted_sequence"] == 0 or lot["leader_id"] is None
            else (
                "reserve_not_met"
                if lot["reserve_minor"] is not None
                and lot["current_minor"] < lot["reserve_minor"]
                else None
            )
        )
        winner = None if reason else lot["leader_id"]
        updated = await transition(
            tx,
            auction_id,
            expected_revision=lot["revision"],
            expected_end_version=lot["end_version"],
            from_mode="bidding",
            to_mode="closed_no_sale" if reason else "closed_winner",
        )
        quote_request = (
            {
                "auction_id": str(auction_id),
                "expected_revision": updated["revision"],
                "source_id": str(auction_id),
                "watch_id": str(lot["watch_id"]),
                "listing_id": str(lot["listing_id"]),
                "buyer_id": str(winner),
                "seller_id": str(lot["seller_id"]),
                "organization_id": str(lot["seller_organization_id"])
                if lot["seller_organization_id"]
                else None,
                "currency": lot["currency"],
                "price_minor": lot["current_minor"],
                "end_version": lot["end_version"],
                "close_version": updated["close_version"],
                "kind": "winner",
            }
            if winner
            else None
        )
        row = await tx.fetchrow(
            """INSERT INTO l13_auction_closes(auction_id,id,end_version,close_version,winner_id,closing_minor,state,reason,quote_request,scheduled_ends_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10) RETURNING *""",
            auction_id,
            uuid4(),
            lot["end_version"],
            updated["close_version"],
            winner,
            lot["current_minor"],
            "allocation_pending" if winner else "no_sale",
            reason,
            json.dumps(quote_request),
            scheduled_end,
        )
        row = await bind_follow_up(tx, app, row)
        if winner is not None:
            await retain_support(tx, row, listing_id=lot['listing_id'], watch_id=lot['watch_id'])
        await enqueue(
            tx,
            EventEnvelope(
                type="auction.close-decided.v1",
                source="auction",
                subject=str(auction_id),
                request_id=request_id,
                data={
                    "auction_id": str(auction_id),
                    "listing_id": str(lot["listing_id"]),
                    "end_version": lot["end_version"],
                    "close_version": updated["close_version"],
                    "outcome": "winner_pending" if winner else "no_sale",
                    "reason": reason,
                    "current_minor": lot["current_minor"],
                    "currency": lot["currency"],
                },
            ),
            ["communications-auction-results"],
        )
        return public(row, lot["currency"], version=2)
