"""Durable follow-up deadlines do not alter the commercial decision."""

from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work


async def escalate_overdue(app):
    async with unit_of_work(app.state.pool) as tx:
        rows = await tx.fetch(
            """WITH due AS (
                SELECT auction_id FROM l13_auction_closes
                WHERE state IN ('allocation_pending','allocation_denied','ended_legacy_review')
                AND escalation_due_at<=clock_timestamp() AND escalated_at IS NULL
                ORDER BY escalation_due_at,auction_id LIMIT 10 FOR UPDATE SKIP LOCKED
            ) UPDATE l13_auction_closes c SET escalated_at=clock_timestamp()
            FROM due WHERE c.auction_id=due.auction_id RETURNING c.*"""
        )
        for row in rows:
            await enqueue(tx, EventEnvelope(
                type="auction.close-follow-up-overdue.v3", source="auction",
                subject=str(row["auction_id"]), request_id="close-follow-up-" + str(row["id"]),
                data={"operation_id": str(row["id"]), "auction_id": str(row["auction_id"]),
                      "responsible_operator_id": str(row["responsible_operator_id"]) if row["responsible_operator_id"] else None,
                      "next_action": row["next_action"],
                      "response_due_at": row["response_due_at"].isoformat(),
                      "escalation_due_at": row["escalation_due_at"].isoformat(),
                      "assignment_required": row["responsible_operator_id"] is None},
            ), ["communications-auction-results"])
