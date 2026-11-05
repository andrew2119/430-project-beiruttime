"""The kernel serializes final price/leader/end; this module owns only durable close intent."""

import hashlib
import json
from uuid import uuid4
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app.kernel import lock_lot, server_now, transition


def public(row, currency=None):
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
        "closing_minor": row["closing_minor"],
        "currency": currency or row.get("currency"),
        "order_available": row["order_id"] is not None,
    }


async def close(app, auction_id, expected_end_version, request_id):
    async with unit_of_work(app.state.pool) as tx:
        lot = await lock_lot(tx, auction_id)
        prior = await tx.fetchrow(
            "SELECT * FROM l13_auction_closes WHERE auction_id=$1", auction_id
        )
        if prior:
            return public(prior, lot["currency"])
        if lot["end_version"] != expected_end_version:
            raise PublicError(
                "stale_end_version",
                "The auction end changed; discard the old close job.",
                status=409,
            )
        now = await server_now(tx)
        if now < lot["ends_at"]:
            raise PublicError(
                "auction_not_ended",
                "The current authoritative end has not passed.",
                status=409,
            )
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
            """INSERT INTO l13_auction_closes(auction_id,id,end_version,close_version,winner_id,closing_minor,state,reason,quote_request)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb) RETURNING *""",
            auction_id,
            uuid4(),
            lot["end_version"],
            updated["close_version"],
            winner,
            lot["current_minor"],
            "allocation_pending" if winner else "no_sale",
            reason,
            json.dumps(quote_request),
        )
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
        return public(row, lot["currency"])
