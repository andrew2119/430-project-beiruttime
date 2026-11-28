"""Versioned adapters; the runtime supplies current scope and E03 access."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, Path, Query

from .current import Provider, Request, read_accepted


@dataclass(frozen=True)
class ReadContext:
    actor_id: str
    organization_id: str | None
    subject_id: str
    watch_id: str
    provider: Provider | None


def create_router(guidance: dict, current_context: Callable) -> APIRouter:
    """Context resolves the path record under the authenticated current identity."""
    if guidance.get("schema_version") != "help-policies.v1":
        raise ValueError("invalid_guidance")
    public_document = deepcopy(guidance)
    router = APIRouter(prefix="/v1/help-policies")

    @router.get("")
    async def public_guidance():
        return deepcopy(public_document)

    @router.get("/accepted-terms/{record_id}")
    async def accepted_terms(
        record_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9._:-]{1,128}$")],
        expected_revision: int = Query(ge=1, le=9_007_199_254_740_991),
        operation_id: str = Header(alias="Operation-Id", pattern=r"^[A-Za-z0-9._:-]{1,128}$"),
        context: ReadContext = Depends(current_context),
    ):
        from fastapi.responses import JSONResponse
        try:
            request = Request(operation_id, context.actor_id, context.organization_id,
                              context.subject_id, context.watch_id, record_id, expected_revision)
        except ValueError:
            return JSONResponse({"code": "invalid_reference"}, status_code=422,
                                headers={"Cache-Control": "no-store"})
        result = await read_accepted(request, context.provider, lambda: datetime.now(timezone.utc))
        status = {"ready": 200, "pending": 202, "denied": 403,
                  "stale": 409, "unavailable": 503}[result["state"]]
        return JSONResponse(result, status_code=status, headers={"Cache-Control": "no-store"})

    return router
