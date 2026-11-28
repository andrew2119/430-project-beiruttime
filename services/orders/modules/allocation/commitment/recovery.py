"""Immutable historical release receipts without reviving stock or payment time."""


async def recover_releases(tx):
    # Only an actual retained release audit establishes the original release time.
    # Absent or ambiguous history remains unavailable for recorded reconciliation.
    rows = await tx.fetch(
        """SELECT o.id,o.watch_id,o.revision,a.occurred_at FROM l08_orders o
        JOIN l08_audit a ON a.resource_id=o.id AND a.revision=o.revision
          AND a.action='expiry-release'
        WHERE o.state='expired_released' AND o.currency='USD'
        AND NOT EXISTS (SELECT 1 FROM l13_payment_attempts p WHERE p.order_id=o.id)
        AND NOT EXISTS (SELECT 1 FROM l13_unpaid_release_receipts r WHERE r.order_id=o.id)
        AND (SELECT count(*) FROM l08_audit h WHERE h.resource_id=o.id
             AND h.revision=o.revision AND h.action='expiry-release')=1
        ORDER BY o.created_at,o.id LIMIT 25 FOR UPDATE OF o SKIP LOCKED"""
    )
    for row in rows:
        await tx.execute(
            """INSERT INTO l13_unpaid_release_receipts
            (order_id,watch_id,order_revision,released_at,attempt_count,origin)
            VALUES($1,$2,$3,$4,0,'historical') ON CONFLICT(order_id) DO NOTHING""",
            row["id"], row["watch_id"], row["revision"], row["occurred_at"],
        )
    return len(rows)
