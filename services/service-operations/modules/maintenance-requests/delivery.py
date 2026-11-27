"""Deliver assessment requests and retain exhausted deliveries for recovery."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
from fastapi import HTTPException

from .provider import Provider

from asyncpg import InterfaceError, PostgresError

from bt_runtime.app.db import unit_of_work


async def escalate_due(tx, operator_id, *, event_id=None):
    """Persist due escalation before any transition can clear the hold."""
    scope = 'AND event_id = $2' if event_id is not None else ''
    args = (operator_id, event_id) if event_id is not None else (operator_id,)
    await tx.execute(f"""
        WITH due AS (
            SELECT event_id FROM maintenance_request_outbox
            WHERE escalation_started_at <= statement_timestamp() - interval '48 hours'
              AND delivered_at IS NULL AND escalated_at IS NULL {scope}
            ORDER BY escalation_started_at, event_id LIMIT 100 FOR UPDATE SKIP LOCKED
        ), escalated AS (
            UPDATE maintenance_request_outbox o SET escalated_at = statement_timestamp()
            FROM due WHERE o.event_id = due.event_id
            RETURNING o.event_id, o.escalation_started_at, $1::uuid AS responsible_operator, o.escalated_at
        )
        INSERT INTO maintenance_delivery_escalations (event_id, held_at, operator_id, escalated_at)
        SELECT event_id, escalation_started_at, responsible_operator, escalated_at FROM escalated
    """, *args)


async def claim_batch(tx, operator_id):
    # Current recovery ownership follows the configured successor. Keep the
    # original hold instant so reassignment cannot restart either deadline.
    await tx.execute("""
        WITH reassigned AS (
            SELECT event_id FROM maintenance_request_outbox
            WHERE held_at IS NOT NULL AND operator_id <> $1
            ORDER BY held_at, event_id LIMIT 100 FOR UPDATE SKIP LOCKED
        )
        UPDATE maintenance_request_outbox o SET operator_id = $1
        FROM reassigned r WHERE o.event_id = r.event_id
    """, operator_id)
    # Commit reservations before attempting delivery so rollback and restart count
    # against the budget. The due time doubles as the reservation fence.
    await tx.execute("""
        WITH exhausted AS (
            SELECT event_id FROM maintenance_request_outbox
            WHERE delivered_at IS NULL AND held_at IS NULL AND attempts = 8
              AND next_attempt_at <= statement_timestamp()
            ORDER BY next_attempt_at, event_id LIMIT 100 FOR UPDATE SKIP LOCKED
        )
        UPDATE maintenance_request_outbox o
        SET held_at = statement_timestamp(), operator_id = $1,
            escalation_started_at = COALESCE(o.escalation_started_at, statement_timestamp())
        FROM exhausted e WHERE o.event_id = e.event_id
    """, operator_id)
    await escalate_due(tx, operator_id)
    return await tx.fetch("""
        WITH due AS (
            SELECT event_id FROM maintenance_request_outbox
            WHERE delivered_at IS NULL AND held_at IS NULL AND attempts < 8
              AND next_attempt_at <= statement_timestamp()
            ORDER BY next_attempt_at, event_id LIMIT 10 FOR UPDATE SKIP LOCKED
        )
        UPDATE maintenance_request_outbox o
        SET attempts = attempts + 1, next_attempt_at = statement_timestamp() + interval '1 minute'
        FROM due WHERE o.event_id = due.event_id
        RETURNING o.event_id, o.next_attempt_at
    """)


async def deliver(tx, event_id, reserved_until, *, operator_id):
    await tx.execute("""
        WITH pending AS (
            SELECT o.event_id, o.request_id, r.organization_id, o.escalation_started_at, o.escalated_at
            FROM maintenance_request_outbox o
            JOIN maintenance_requests r ON r.id = o.request_id
            WHERE o.event_id = $1 AND o.next_attempt_at = $2
              AND o.delivered_at IS NULL AND o.held_at IS NULL
              AND o.event_type = 'service-operations.maintenance.submitted.v1'
            FOR UPDATE OF o
        ), delivered AS (
            INSERT INTO maintenance_assessment_inbox
                (event_id, request_id, organization_id, delivered_at)
            SELECT event_id, request_id, organization_id, clock_timestamp()
            FROM pending
            RETURNING event_id, delivered_at
        ), escalated AS (
            INSERT INTO maintenance_delivery_escalations (event_id, held_at, operator_id, escalated_at)
            SELECT p.event_id, p.escalation_started_at, $3::uuid, d.delivered_at
            FROM pending p JOIN delivered d USING (event_id)
            WHERE p.escalated_at IS NULL
              AND p.escalation_started_at + interval '48 hours' <= d.delivered_at
            RETURNING event_id, escalated_at
        )
        UPDATE maintenance_request_outbox o
        SET delivered_at = d.delivered_at, escalated_at = COALESCE(e.escalated_at, o.escalated_at)
        FROM delivered d LEFT JOIN escalated e USING (event_id)
        WHERE o.event_id = d.event_id
    """, event_id, reserved_until, operator_id)


async def fence_operator(tx, held_until):
    now = await tx.fetchval('SELECT clock_timestamp()')
    deadline = min(now + timedelta(seconds=3), held_until)
    milliseconds = int((deadline - now - timedelta(seconds=1)).total_seconds() * 1_000)
    if milliseconds <= 0:
        raise ConnectionError('maintenance_recovery_unavailable')
    await tx.execute("SELECT set_config('transaction_timeout', $1, true)", f'{milliseconds}ms')


async def run_delivery(app, stop):
    while not stop.is_set():
        operator_id = getattr(app.state, 'maintenance_delivery_operator_id', None)
        authority = Provider(SimpleNamespace(app=app, state=SimpleNamespace(request_id=str(uuid4()))))
        try:
            held_until = await authority.delivery_authority_until(operator_id) if isinstance(operator_id, UUID) else None
            if held_until is None:
                # Keep attempts and earlier deadlines intact until an authorized successor is available.
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except TimeoutError:
                    continue
                return
            async with unit_of_work(app.state.pool) as tx:
                await fence_operator(tx, held_until)
                reservations = await claim_batch(tx, operator_id)
            for reservation in reservations:
                if stop.is_set():
                    return
                try:
                    held_until = await authority.delivery_authority_until(operator_id)
                    if held_until is None:
                        break
                    async with unit_of_work(app.state.pool) as tx:
                        await fence_operator(tx, held_until)
                        await deliver(tx, reservation['event_id'], reservation['next_attempt_at'],
                                      operator_id=operator_id)
                except (OSError, InterfaceError, PostgresError, HTTPException, TimeoutError):
                    # The committed reservation becomes due again independently.
                    continue
        except (OSError, InterfaceError, PostgresError, HTTPException, TimeoutError):
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except TimeoutError:
            pass
