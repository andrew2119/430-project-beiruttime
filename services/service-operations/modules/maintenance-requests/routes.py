"""Request transport. Composition supplies the current-authority provider."""
import asyncio
import json
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException
from bt_contracts.service.maintenance.v1 import Request as MaintenanceRequest, Context, Photo
from bt_runtime.app.db import unit_of_work
from .commands import submit, lookup, Rejected
from .provider import Provider, identity as current_identity

router = APIRouter(prefix='/v1/maintenance', tags=['maintenance requests'])

async def identity(request: Request):
    resolver = getattr(request.app.state, 'maintenance_identity', None)
    if resolver is None:
        resolver = current_identity
    try:
        return await asyncio.wait_for(resolver(request), timeout=1.2)
    except (TimeoutError, ConnectionError):
        raise HTTPException(503) from None

@router.post('/requests', status_code=201)
async def create(body: MaintenanceRequest, request: Request, actor_id=Depends(identity)):
    provider = getattr(request.app.state, 'maintenance_provider', None) or Provider(request)
    if provider is None:
        raise HTTPException(503)
    def transaction(operation_id):
        return unit_of_work(request.app.state.pool, lock_key=f'maintenance:{operation_id}')
    try:
        return await submit(body, actor_id=actor_id, provider=provider, transaction=transaction)
    except Rejected as error:
        code = str(error)
        raise HTTPException({'denied':403,'stale':409,'operation_conflict':409,
            'assessment_permission_required':422,'pending':503}.get(code,503), detail=code) from None

@router.get('/operations/{operation_id}')
async def operation(operation_id: UUID, organization_id: UUID, request: Request, actor_id=Depends(identity)):
    provider = getattr(request.app.state, 'maintenance_provider', None) or Provider(request)
    if provider is None:
        raise HTTPException(503)
    async with request.app.state.pool.acquire() as tx:
        row = await lookup(operation_id, actor_id=actor_id, organization_id=organization_id, tx=tx)
    if row is None:
        raise HTTPException(404)
    try:
        allowed = await asyncio.wait_for(provider.operation_access(
            actor_id, organization_id, operation_id, row['watch_id'], row['intervention']), timeout=1.2)
    except (TimeoutError, ConnectionError):
        raise HTTPException(503) from None
    if allowed is not True:
        raise HTTPException(403)
    return json.loads(row['result'])

@router.get('/context/{watch_id}', response_model=Context)
async def context(watch_id: UUID, request: Request, actor_id=Depends(identity)):
    provider = getattr(request.app.state, 'maintenance_provider', None) or Provider(request)
    if provider is None:
        raise HTTPException(503)
    try:
        value = Context.model_validate(await asyncio.wait_for(provider.context(actor_id, watch_id), timeout=1.2))
    except (TimeoutError, ConnectionError, ValueError):
        raise HTTPException(503) from None
    if value.actor_id != actor_id or value.subject_id != actor_id or value.watch_id != watch_id:
        raise HTTPException(403)
    return value

@router.post('/photos')
async def photo(body: Photo, request: Request, actor_id=Depends(identity)):
    import base64
    import binascii
    if not body.safe_photo_declared:
        raise HTTPException(422)
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422) from None
    signatures = {'image/jpeg': content.startswith(b'\xff\xd8\xff'),
        'image/png': content.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/webp': content.startswith(b'RIFF') and content[8:12] == b'WEBP'}
    if not 1 <= len(content) <= 262144 or not signatures[body.media_type]:
        raise HTTPException(422)
    provider = getattr(request.app.state, 'maintenance_provider', None) or Provider(request)
    if provider is None:
        raise HTTPException(503)
    # The provider atomically rechecks scope, strips metadata, enforces ten files
    # per request and stores a stable private receipt before acknowledging it.
    try:
        reference = await asyncio.wait_for(provider.store_photo(actor_id, body, content), timeout=1.2)
        reference = UUID(str(reference))
    except (TimeoutError, ConnectionError, ValueError):
        raise HTTPException(503) from None
    return {'photo_ref': reference}
