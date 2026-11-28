"""Composition supplies current identity and durable provider dependencies."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from .reader import Read
from .publication import Publication, publish, lookup_publication
from pydantic import BaseModel, ConfigDict, Field


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    job_ids: tuple[UUID, ...] = Field(max_length=50)


def build_router(reader, current_context):
    router = APIRouter(prefix='/v1/history', tags=['history'])

    @router.get('/operations/{operation_id}')
    async def lookup(operation_id: UUID, context=Depends(current_context)):
        try:
            result = await reader.lookup(operation_id, context.actor_id, context.subject_id, context.organization_id)
        except TimeoutError:
            raise HTTPException(503) from None
        if result is None:
            raise HTTPException(404)
        return result

    @router.get('/{watch_id}')
    async def read(watch_id: UUID, operation_id: UUID, expected_revision: int = Query(ge=0),
                   page: int = Query(default=0, ge=0, le=10000),
                   page_size: int = Query(default=20, ge=1, le=50), context=Depends(current_context)):
        return await reader.read(Read(operation_id, context.actor_id, context.subject_id,
            watch_id, context.organization_id, expected_revision, page, page_size))

    @router.post('/{watch_id}/publication')
    async def publication(watch_id: UUID, body: PublishBody, context=Depends(current_context)):
        read = Read(body.operation_id, context.actor_id, context.subject_id,
            watch_id, context.organization_id, body.expected_revision)
        try:
            command = Publication(body.operation_id, context.actor_id, context.subject_id,
                context.organization_id, watch_id, body.expected_revision, body.job_ids)
        except ValueError:
            raise HTTPException(422) from None
        return await publish(reader.provider, reader, read, command)

    @router.get('/publication/operations/{operation_id}')
    async def publication_lookup(operation_id: UUID, context=Depends(current_context)):
        try:
            result = await lookup_publication(reader.provider, reader, operation_id, context)
        except (TimeoutError, OSError, ValueError):
            raise HTTPException(503) from None
        if result is None:
            raise HTTPException(404)
        return result

    return router
