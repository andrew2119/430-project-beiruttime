"""Private route adapter; absent current-authority integration fails closed."""
from uuid import UUID
from pydantic import ValidationError
from bt_contracts_core.errors import error_body
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from bt_contracts.eligibility.private_review.models import Command
from .repository import Repository
from .review import ReviewError, ReviewService

router = APIRouter(prefix='/v1/private-reviews')
MESSAGES = {
    403: ('You no longer have access. Ask for a current assignment.', 'لم يعد لديك حق الوصول. اطلب تكليفاً سارياً.'),
    404: ('This operation is unavailable. Check its reference.', 'هذه العملية غير متاحة. تحقق من مرجعها.'),
    409: ('The case changed. Reload before deciding.', 'تغيرت الحالة. أعد تحميلها قبل اتخاذ القرار.'),
    422: ('Check the case fields and reason.', 'تحقق من حقول الحالة والسبب.'),
    503: ('Review is unavailable. Retry the same operation reference.', 'المراجعة غير متاحة. أعد المحاولة باستخدام مرجع العملية نفسه.'),
}


def response(value, status=200):
    return JSONResponse(value, status_code=status, headers={'Cache-Control': 'private, no-store', 'Pragma': 'no-cache'})


def failure(request, status, code):
    en, ar = MESSAGES[status]
    return response(error_body(code, en, getattr(request.state, 'request_id', ''), details={'messages': {'en': en, 'ar': ar}}), status)


async def dispatch(request, case_id, *, command=None, kind='current', page=1, operation_id=None):
    try:
        try:
            case_id = UUID(str(case_id))
            operation_id = UUID(str(operation_id)) if operation_id is not None else None
            page = int(page)
        except (ValueError, TypeError):
            raise ReviewError(422, 'invalid_fields') from None
        header = request.headers.get('authorization', '')
        if not header.startswith('Bearer ') or not header[7:]:
            raise ReviewError(403, 'denied')
        authority = getattr(request.app.state, 'private_review_authority', None)
        if authority is None:
            raise ReviewError(503, 'unavailable')
        service = ReviewService(Repository(request.app.state.pool, request.state.request_id), authority)
        if command is not None:
            if command.case_id != case_id:
                raise ReviewError(403, 'denied')
            value = await service.command(header[7:], command)
        else:
            value = await service.read(header[7:], case_id, kind, page, operation_id)
        return response(value)
    except ReviewError as error:
        return failure(request, error.status, error.code)


@router.post('/{case_id}/commands')
async def command(case_id: str, request: Request):
    try:
        body = Command.model_validate(await request.json())
    except (ValidationError, ValueError):
        return failure(request, 422, 'invalid_fields')
    return await dispatch(request, case_id, command=body)


@router.get('/{case_id}')
async def current(case_id: str, request: Request):
    return await dispatch(request, case_id)


@router.get('/{case_id}/history')
async def history(case_id: str, request: Request, page: str = '1'):
    return await dispatch(request, case_id, kind='history', page=page)


@router.get('/{case_id}/evidence')
async def evidence(case_id: str, request: Request):
    return await dispatch(request, case_id, kind='evidence')


@router.get('/{case_id}/operations/{operation_id}')
async def operation(case_id: str, operation_id: str, request: Request):
    return await dispatch(request, case_id, kind='operation', operation_id=operation_id)
