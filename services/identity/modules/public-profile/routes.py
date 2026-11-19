"""Composition supplies the current-facts reader; no fixture fallback."""
from uuid import uuid4
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from .profile import read_profile


def create_router(provider):
    router = APIRouter(prefix="/v1/public-profiles")

    @router.get("/{subject_id}")
    async def view(subject_id: str, page: int = Query(default=1, ge=1, le=100000), operation_id: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9-]{1,80}$")):
        try:
            result = await read_profile(provider, subject_id, operation_id or str(uuid4()), page)
        except ValueError:
            return JSONResponse({"code": "invalid_request"}, status_code=400)
        status = {"denied": 403, "stale": 409, "unavailable": 503}.get(result["state"], 200)
        return JSONResponse(result, status_code=status, headers={"Cache-Control": "no-store"})

    return router
