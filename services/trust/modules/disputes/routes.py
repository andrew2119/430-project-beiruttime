"""Composition injects verified credentials and a durable dispute service."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
import hashlib
import base64
import re
from .contracts import Command
from .service import Rejected


def router_for(service, current_credential):
    router = APIRouter(prefix='/v1/disputes', tags=['disputes'])

    def failure(error):
        status = {'denied': 403, 'unavailable': 503, 'stale': 409, 'conflict': 409,
                  'late': 409, 'prerequisites': 409, 'pending': 409}.get(error.code, 422)
        return JSONResponse({'error': {'code': error.code, 'message': error.code, 'details': {'closing_at': error.closing_at}}}, status_code=status, headers={'Cache-Control': 'no-store'})

    @router.post('/commands')
    async def command(request: Request, credential=Depends(current_credential)):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 40_000:
                raise HTTPException(413, detail={'code': 'invalid'})
        try:
            body = Command.model_validate_json(raw)
        except ValueError:
            raise HTTPException(422, detail={'code': 'invalid'}) from None
        try:
            return JSONResponse(await service.command(credential, body), headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return failure(error)

    @router.post('/evidence/{subject_id}')
    async def evidence(subject_id: str, request: Request, organization_id: str | None = None,
                       credential=Depends(current_credential)):
        try:
            await service.authority(credential, subject_id, organization_id)
            method = getattr(service.providers, 'stage', None)
            if method is None:
                raise Rejected('unavailable')
            operation = request.headers.get('Idempotency-Key', '')
            checksum = request.headers.get('X-Content-SHA256', '')
            media = request.headers.get('Content-Type', '')
            if not re.fullmatch(r'[a-zA-Z0-9_-]{8,128}', operation) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
                raise Rejected('evidence')
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 5_000_000:
                    raise Rejected('evidence')
            signatures = {'image/jpeg': b'\xff\xd8\xff', 'image/png': b'\x89PNG\r\n\x1a\n', 'application/pdf': b'%PDF-'}
            if media not in signatures or not raw.startswith(signatures[media]) or hashlib.sha256(raw).hexdigest() != checksum:
                raise Rejected('evidence')
            result = await service.bounded(method(credential, subject_id, organization_id, operation, bytes(raw), media, checksum))
            from .contracts import _contract
            accepted = _contract.Evidence.model_validate(result)
            # Upload integrity covers incoming bytes; the reference covers sanitized storage.
            if accepted.media_type != media:
                raise Rejected('unavailable')
            return JSONResponse(accepted.model_dump(), headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return failure(error)
        except ValueError:
            return failure(Rejected('unavailable'))

    @router.get('/evidence/{subject_id}/{reference}')
    async def download(subject_id: str, reference: str, organization_id: str | None = None,
                       credential=Depends(current_credential)):
        try:
            context = await service.context(credential, subject_id, organization_id)
            case = context['case'] or {}
            items = case.get('evidence', []) + case.get('response', {}).get('evidence', []) + case.get('decision', {}).get('evidence', [])
            item = next((item for item in items if item['reference'] == reference), None)
            method = getattr(service.providers, 'download', None)
            if not item:
                raise Rejected('denied')
            if method is None:
                raise Rejected('unavailable')
            content = await service.bounded(method(credential, subject_id, organization_id, reference))
            if not isinstance(content, bytes) or len(content) != item['size'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                raise Rejected('unavailable')
            # Revalidate scope after a protected file read, before releasing bytes.
            await service.authority(credential, subject_id, organization_id)
            return JSONResponse({'content_base64': base64.b64encode(content).decode(), 'media_type': item['media_type']}, headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return failure(error)

    @router.get('/operations/{operation_id}')
    async def operation(operation_id: str, subject_id: str, organization_id: str | None = None,
                        credential=Depends(current_credential)):
        if len(operation_id) > 128 or len(subject_id) > 128:
            raise HTTPException(422, detail={'code': 'invalid'})
        try:
            return JSONResponse(await service.read(credential, subject_id, organization_id, operation_id), headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return failure(error)

    @router.get('/{subject_id}')
    async def detail(subject_id: str, organization_id: str | None = None,
                     credential=Depends(current_credential)):
        if len(subject_id) > 128 or (organization_id and len(organization_id) > 128):
            raise HTTPException(422, detail={'code': 'invalid'})
        try:
            return JSONResponse(await service.context(credential, subject_id, organization_id), headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return failure(error)

    return router
