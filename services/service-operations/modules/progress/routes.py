"""Additive HTTP adapter; current-provider composition is mandatory."""
import asyncio
from asyncpg import (CannotConnectNowError, LockNotAvailableError, PostgresConnectionError,
                     QueryCanceledError, TooManyConnectionsError)
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from bt_contracts_core.errors import PublicError
from .contracts import Access, Command
from .model import Denied, authorize
from .service import execute, read, current
from .store import Store, decoded

class ProgressRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise PublicError(
                    'invalid_parameters',
                    'Check the complete job and operation references and integer page offset, then retry with the same operation reference. / تحقّق من مرجعي الطلب والعملية الكاملين وإزاحة الصفحة الصحيحة، ثم أعد المحاولة بمرجع العملية نفسه.',
                    status=422) from None

        return validated


router = APIRouter(prefix='/v1/progress', tags=['progress'], route_class=ProgressRoute)


async def access_for(request):
    adapter = getattr(request.app.state, 'progress_access', None)
    provider = getattr(request.app.state, 'progress_source', None)
    if adapter is None or provider is None:
        raise Denied('unavailable', 503)
    try:
        async with asyncio.timeout(1.2):
            access = Access.model_validate(await adapter(request))
        return access, provider
    except (TimeoutError, ConnectionError, ValueError, TypeError, KeyError):
        raise Denied('unavailable', 503) from None


async def respond(request, action):
    try:
        access, provider = await access_for(request)
        async with request.app.state.pool.acquire(timeout=1.2) as tx:
            async with tx.transaction():
                return await action(Store(tx), provider, access)
    except (TimeoutError, ConnectionError, PostgresConnectionError, CannotConnectNowError,
            TooManyConnectionsError, LockNotAvailableError, QueryCanceledError):
        raise PublicError('unavailable',
                          'Progress is unavailable. Retry with the same operation reference. / التقدّم غير متاح. أعد المحاولة بمرجع العملية نفسه.',
                          status=503) from None
    except Denied as error:
        raise PublicError(error.code,
                          'Check current access and progress, then retry with the same operation reference. / تحقّق من الصلاحية الحالية والتقدّم، ثم أعد المحاولة بمرجع العملية نفسه.',
                          status=error.status) from None


@router.get('/{subject_id}')
async def detail(subject_id: UUID, request: Request, offset: int = 0):
    return await respond(request, lambda store, provider, access: read(store, provider, access, subject_id, offset))


@router.post('/{subject_id}')
async def report(subject_id: UUID, request: Request):
    body = bytearray()
    try:
        async with asyncio.timeout(4):
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 32768:
                    raise PublicError('body_too_large',
                                      'Report exceeds 32 KiB. Shorten the report and retry with the same operation reference. / يتجاوز التقرير 32 كيبيبايت. اختصر التقرير وأعد المحاولة بمرجع العملية نفسه.',
                                      status=413)
    except TimeoutError:
        raise PublicError('request_timeout',
                          'Report upload timed out. Retry the same report with the same operation reference. / انتهت مهلة إرسال التقرير. أعد إرسال التقرير نفسه بمرجع العملية نفسه.',
                          status=408) from None
    try:
        command = Command.model_validate_json(body)
    except ValueError:
        raise PublicError('invalid_command',
                          'Report is invalid. Check required fields and UTC times, then retry with the same operation reference. / التقرير غير صالح. تحقّق من الحقول المطلوبة والأوقات بالتوقيت العالمي ثم أعد المحاولة بمرجع العملية نفسه.',
                          status=422) from None
    if command.subject_id != subject_id:
        raise PublicError('subject_mismatch',
                          'Job references differ. Check the job reference before retrying with the same operation reference. / مرجعا الطلب مختلفان. تحقّق من مرجع الطلب قبل إعادة المحاولة بمرجع العملية نفسه.',
                          status=409)
    return await respond(request, lambda store, provider, access: execute(store, provider, access, command))


@router.get('/{subject_id}/operations/{operation_id}')
async def operation(subject_id: UUID, operation_id: UUID, request: Request):
    async def lookup(store, provider, access):
        source = await current(provider, access, subject_id)
        authorize(access, source, datetime.now(timezone.utc), write=True)
        receipt = await store.receipt(operation_id)
        authorize(access, source, datetime.now(timezone.utc), write=True)
        if not receipt or receipt['actor_id'] != access.actor_id or receipt['subject_id'] != subject_id or receipt['organization_id'] != access.organization_id:
            raise Denied('operation_missing', 404)
        return decoded(receipt['result'])
    return await respond(request, lookup)
