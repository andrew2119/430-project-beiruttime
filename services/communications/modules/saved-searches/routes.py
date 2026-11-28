"""Private operations; current identity is resolved before every durable lookup."""
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, StrictInt
from bt_contracts_core.models import Contract
from bt_contracts.comms.saved_searches.models import Command
from bt_runtime.app.db import unit_of_work
from service_app.security import actor
from . import service
from .http import BoundedRoute

router = APIRouter(prefix='/v1/saved-searches', tags=['saved-searches'], route_class=BoundedRoute)


async def buyer(request: Request, owner=Depends(actor)):
    if 'buyer' not in request.state.principal.roles:
        service.fail('denied', 403)
    return owner


def provider(request):
    return getattr(request.app.state, 'saved_search_catalog', None)


@router.post('/commands')
async def save(body: Command, request: Request, owner=Depends(buyer)):
    async with unit_of_work(request.app.state.pool, lock_key='saved-searches:' + str(owner)) as tx:
        return await service.command(tx, owner, body, provider(request))


@router.get('/operations/{operation_id}')
async def operation(operation_id: UUID, request: Request, owner=Depends(buyer)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT result FROM l22_search_operations WHERE owner_id=$1 AND operation_id=$2', owner, operation_id)
    if row is None:
        service.fail('not_found', 404)
    return service.decoded(row['result'])


async def page(request, owner, offset, limit, notices=False):
    table = 'l22_match_notices' if notices else 'l22_saved_searches'
    condition = 'NOT cleared' if notices else "state='saved'"
    order = 'event_time DESC,id DESC' if notices else 'created_at DESC,id DESC'
    async with request.app.state.pool.acquire() as tx:
        async with tx.transaction(isolation='repeatable_read', readonly=True):
            total = await tx.fetchval(f'SELECT count(*) FROM {table} WHERE owner_id=$1 AND {condition}', owner)
            rows = await tx.fetch(f'SELECT * FROM {table} WHERE owner_id=$1 AND {condition} ORDER BY {order} OFFSET $2 LIMIT $3', owner, offset, limit)
    items = []
    for row in rows:
        if not notices:
            items.append(service.project(row))
        else:
            items.append({key: value.isoformat() if key == 'event_time' else str(value) if isinstance(value, UUID) else value
                          for key, value in dict(row).items() if key not in ('owner_id', 'occurrence_id')})
    return {'items': items, 'total': total, 'offset': offset, 'limit': limit}


@router.get('')
async def searches(request: Request, owner=Depends(buyer), offset: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=20)):
    return await page(request, owner, offset, limit)


@router.get('/notices')
async def notices(request: Request, owner=Depends(buyer), offset: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=20)):
    return await page(request, owner, offset, limit, True)


class Mutation(Contract):
    expected_revision: StrictInt = Field(ge=1)


async def mutate(identifier, body, request, owner, field):
    async with unit_of_work(request.app.state.pool, lock_key='saved-searches:' + str(owner)) as tx:
        row = await tx.fetchrow('SELECT * FROM l22_match_notices WHERE id=$1 AND owner_id=$2 FOR UPDATE', identifier, owner)
        if row is None:
            service.fail('not_found', 404)
        # Setting the same bit is a naturally idempotent retry, even after response loss.
        if not row[field]:
            if row['revision'] != body.expected_revision:
                service.fail('stale_revision')
            await tx.execute(f'UPDATE l22_match_notices SET {field}=true,revision=revision+1 WHERE id=$1 AND owner_id=$2', identifier, owner)
    return {'state': field}


@router.post('/notices/{identifier}/read')
async def read(identifier: UUID, body: Mutation, request: Request, owner=Depends(buyer)):
    return await mutate(identifier, body, request, owner, 'read')


@router.post('/notices/{identifier}/clear')
async def clear(identifier: UUID, body: Mutation, request: Request, owner=Depends(buyer)):
    return await mutate(identifier, body, request, owner, 'cleared')


@router.get('/notices/{identifier}/destination')
async def destination(identifier: UUID, request: Request, owner=Depends(buyer)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM l22_match_notices WHERE id=$1 AND owner_id=$2 AND NOT cleared', identifier, owner)
    if not row:
        service.fail('not_found', 404)
    visible = await service.call(provider(request), 'visible', row['listing_id'], row['source_revision'])
    if visible is not True:
        service.fail('not_found', 404)
    return {'href': '/watches/' + str(row['listing_id'])}
