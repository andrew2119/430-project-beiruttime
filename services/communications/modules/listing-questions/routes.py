"""Additive route factory; composition supplies current authentication and storage."""
import json
import asyncio
import sqlite3
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .adapter import dispatch
from .model import Rejected

ERRORS = {
    'invalid': (422, 'Check the question and action reference.', 'تحقق من السؤال ومرجع الإجراء.'),
    'denied': (403, 'Current access does not permit this action.', 'صلاحيتك الحالية لا تسمح بهذا الإجراء.'),
    'stale': (409, 'Refresh and review the current listing.', 'حدّث الإعلان الحالي وراجعه.'),
    'conflict': (409, 'This action reference belongs to another request.', 'مرجع الإجراء مرتبط بطلب آخر.'),
    'unavailable': (503, 'Access is unavailable. Retry the same action reference.', 'التحقق من الصلاحية غير متاح. أعد المحاولة بمرجع الإجراء نفسه.'),
}


def build_router(store, authenticate):
    router = APIRouter(prefix='/v1/listing-questions')

    async def invoke(request, listing, operation, payload):
        try:
            if not 1 <= len(listing) <= 200:
                raise Rejected('invalid')
            if operation in ('list', 'review'):
                pages = ('page',) if operation == 'list' else ('reports_page', 'appeals_page')
                for key in pages:
                    value = payload[key]
                    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 5 or not 0 <= int(value) <= 50000:
                        raise Rejected('invalid')
                    payload[key] = int(value)
            principal = await asyncio.wait_for(authenticate(request), 1.2)
            return await dispatch(store, principal, listing, operation, payload)
        except (TimeoutError, OSError, sqlite3.OperationalError):
            status, en, ar = ERRORS['unavailable']
            return JSONResponse(status_code=status, content={'error': {'code': 'unavailable', 'request_id': getattr(request.state, 'request_id', ''), 'message': {'en': en, 'ar': ar}, 'details': {}}})
        except Rejected as error:
            code = str(error)
            status, en, ar = ERRORS.get(code, ERRORS['unavailable'])
            return JSONResponse(status_code=status, content={'error': {'code': code, 'request_id': getattr(request.state, 'request_id', ''), 'message': {'en': en, 'ar': ar}, 'details': {}}})

    async def body(request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 16384:
                return None
        try:
            return json.loads(data)
        except (ValueError, UnicodeError):
            return None

    @router.get('/{listing}')
    async def listing(listing: str, request: Request, page: str = '0'):
        return await invoke(request, listing, 'list', {'page': page})

    @router.get('/{listing}/operations/{operation_id}')
    async def lookup(listing: str, operation_id: str, request: Request):
        return await invoke(request, listing, 'lookup', {'operation_id': operation_id})

    @router.get('/{listing}/review/{question_id}')
    async def review(listing: str, question_id: str, request: Request, reports_page: str = '0', appeals_page: str = '0'):
        return await invoke(request, listing, 'review', {'question_id': question_id, 'reports_page': reports_page, 'appeals_page': appeals_page})

    @router.post('/{listing}/suggest')
    async def suggest(listing: str, request: Request):
        return await invoke(request, listing, 'suggest', await body(request))

    @router.post('/{listing}/commands')
    async def command(listing: str, request: Request):
        return await invoke(request, listing, 'command', await body(request))

    return router
