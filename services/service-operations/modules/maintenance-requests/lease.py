"""Guard local mutations of the request generation the custody peer can lease."""
from fastapi import HTTPException


async def require_request_mutable(tx, request_id, *, predecision=None):
    try:
        from service_app.job_fences import require_maintenance_request_mutable
    except ImportError:
        if await tx.fetchval("SELECT to_regclass('public.service_maintenance_request_leases') IS NOT NULL"):
            raise HTTPException(503) from None
    else:
        await require_maintenance_request_mutable(tx, request_id)
    op,digest=predecision or (None,None)
    if await tx.fetchval('''SELECT 1 FROM maintenance_predecision_leases WHERE request_id=$1
        AND held_until>clock_timestamp() AND (operation_id,binding_hash) IS DISTINCT FROM ($2::uuid,$3::text)''',
        request_id,op,digest):
        raise HTTPException(409,detail={'code':'maintenance_predecision_in_use'})
    if await tx.fetchval('''SELECT 1 FROM maintenance_assessment_destinations
        WHERE request_id=$1 AND held_until>clock_timestamp()''',request_id):
        raise HTTPException(409,detail={'code':'maintenance_destination_in_use'})
