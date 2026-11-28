"""Serialize repair source changes with the current job-authority lease."""
from uuid import UUID

from fastapi import HTTPException


def repair_lock_key(case_id: UUID) -> str:
    return f'service-job-assignment:{case_id}'


async def lock_case(tx, case_id: UUID):
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', repair_lock_key(case_id))


async def require_mutable(tx, case_id: UUID):
    # The job-authority table is installed by the assignment module. Before
    # it is installed, no repair authority can be issued or retained.
    if await tx.fetchval("SELECT to_regclass('public.service_job_authority_leases') IS NOT NULL"):
        held = await tx.fetchval('''SELECT held_until > clock_timestamp()
            FROM public.service_job_authority_leases WHERE kind='repair' AND subject_id=$1''', case_id)
        if held:
            raise HTTPException(409, detail={'code': 'job_authority_in_use'})


async def physical_confirmation(tx, request_id: UUID, opening, *, buyer_id: UUID | None = None) -> bool:
    return bool(await tx.fetchval('''SELECT 1 FROM maintenance_assessment_decisions d
        JOIN maintenance_requests r ON r.id=d.request_id AND r.revision=d.request_revision
        WHERE d.request_id=$1 AND d.state='confirmed' AND d.order_id=$2
          AND d.organization_id=$3 AND d.watch_id=$4 AND d.watch_revision=$5
          AND d.custody_receipt_id=$6 AND d.custody_receipt_revision=$7 AND d.incident_revision=$8
          AND ($9::uuid IS NULL OR r.actor_id=$9)''', request_id, opening.order_id,
        opening.organization_id, opening.watch_id, opening.watch_revision, opening.receipt_id,
        opening.receipt_revision, opening.incident_revision, buyer_id))
