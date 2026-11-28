"""Additive route factory. Runtime composition supplies authenticated scope and store."""
import asyncio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

COPY = {
    'denied': ('Access denied. Reopen the conversation.', 'الوصول مرفوض. أعد فتح المحادثة.'),
    'stale_revision': ('Conversation changed. Review it again.', 'تغيّرت المحادثة. راجعها مجدداً.'),
    'classified_route_required': ('Use the private case route for identity or payment evidence.', 'استخدم مسار القضية الخاص لإثبات الهوية أو الدفع.'),
    'unsafe_photo': ('Choose a safe photo under 5 MB and 12 million pixels.', 'اختر صورة آمنة دون ٥ ميغابايت و١٢ مليون بكسل.'),
    'photo_limit': ('This conversation has reached its photo limit.', 'بلغت هذه المحادثة الحد الأقصى للصور.'),
    'operation_conflict': ('Keep the original action reference and request.', 'احتفظ بمرجع الإجراء والطلب الأصليين.'),
    'already_attached': ('This photo is already attached.', 'هذه الصورة مرفقة بالفعل.'),
    'invalid_request': ('Review the request and try again.', 'راجع الطلب وحاول مجدداً.'),
    'unavailable': ('Unavailable. Retry the same action reference.', 'غير متاح. أعد المحاولة بمرجع الإجراء نفسه.'),
}

class Attachment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: str = Field(min_length=1, max_length=128)
    photo: str = Field(min_length=1, max_length=128)
    purpose: str
    declaration: StrictBool


def create_router(store, authenticated_scope):
    router = APIRouter(prefix='/v1/message-photos')

    def respond(call, binary=False):
        try:
            result = call()
            headers = store_module_headers()
            return Response(result, media_type='image/jpeg', headers=headers) if binary else JSONResponse(result, headers=headers)
        except Exception as error:
            code = getattr(error, 'code', 'unavailable')
            if code not in COPY:
                code = 'unavailable'
            status = 503 if code == 'unavailable' else 403 if code == 'denied' else 409 if code in ('stale_revision', 'operation_conflict', 'already_attached') else 422
            return failure(code, status)

    def store_module_headers():
        return {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
                'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin',
                'Referrer-Policy': 'no-referrer'}

    def failure(code, status):
        return JSONResponse({'error': {'code': code, 'message': COPY[code][0],
            'request_id': '', 'details': {'messages': dict(zip(('en', 'ar'), COPY[code]))}}},
            status_code=status, headers=store_module_headers())

    @router.post('/uploads')
    async def upload(request: Request, operation: str, purpose: str, declaration: bool, scope=Depends(authenticated_scope)):
        raw = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > 5 * 1024 * 1024:
                        return failure('unsafe_photo', 413)
                    raw.extend(chunk)
        except TimeoutError:
            return failure('unavailable', 503)
        # Decode and bounded storage work run outside the request event loop.
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(respond, lambda: store.command(scope, operation, 'upload', raw=bytes(raw), purpose=purpose, declaration=declaration))

    @router.post('/attachments')
    def attach(body: Attachment, scope=Depends(authenticated_scope)):
        return respond(lambda: store.command(scope, body.operation, 'attach', photo=body.photo, purpose=body.purpose, declaration=body.declaration))

    @router.get('')
    def listing(offset: int = 0, limit: int = 20, scope=Depends(authenticated_scope)):
        return respond(lambda: store.read(scope, 'list', offset=offset, limit=limit))

    @router.get('/operations/{operation}')
    def lookup(operation: str, scope=Depends(authenticated_scope)):
        return respond(lambda: store.read(scope, 'operation', operation=operation))

    @router.get('/{photo}/metadata')
    def metadata(photo: str, scope=Depends(authenticated_scope)):
        return respond(lambda: store.read(scope, 'metadata', photo=photo))

    @router.get('/{photo}/bytes')
    def pixels(photo: str, scope=Depends(authenticated_scope)):
        return respond(lambda: store.read(scope, 'bytes', photo=photo), binary=True)

    return router
