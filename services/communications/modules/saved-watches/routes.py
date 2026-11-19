"""Additive route boundary; the owning service supplies the private store."""
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from bt_contracts_core.errors import PublicError
from service_app.security import actor

from .store import Failure

router = APIRouter(prefix='/v1/saved-watches', tags=['saved-watches'])
MESSAGES = {
    'denied': 'Access denied. / الوصول مرفوض.',
    'stale': 'Reload the current saved watch. / أعد تحميل الساعة المحفوظة الحالية.',
    'conflict': 'Use the original action reference. / استخدم مرجع الإجراء الأصلي.',
    'unavailable': 'Unavailable. Retry the same action. / غير متاح. أعد محاولة الإجراء نفسه.',
    'invalid': 'Review the request. / راجع الطلب.',
}


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal['communications.saved-watches.v1']
    operation_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    saved: bool
    alerts: list[Literal['price', 'bid', 'ending', 'sold']] = Field(max_length=4)


def invoke(request, method, *args):
    store = getattr(request.app.state, 'saved_watches', None)
    if store is None:
        raise PublicError('unavailable', MESSAGES['unavailable'], status=503)
    try:
        return getattr(store, method)(*args)
    except Failure as error:
        status = {'denied': 403, 'stale': 409, 'conflict': 409, 'invalid': 422}.get(error.code, 503)
        raise PublicError(error.code, MESSAGES[error.code], status=status) from None
    except TimeoutError:
        raise PublicError('unavailable', MESSAGES['unavailable'], status=503) from None


@router.get('')
def listing(request: Request, owner=Depends(actor), offset: int = Query(0, ge=0, le=100000),
            limit: int = Query(20, ge=1, le=50)):
    return invoke(request, 'listing', str(owner), str(owner), offset, limit)


@router.get('/operations/{operation_id}')
def lookup(request: Request, operation_id: str = Path(min_length=1, max_length=128), owner=Depends(actor)):
    result = invoke(request, 'lookup', str(owner), str(owner), str(operation_id))
    if result is None:
        raise PublicError('pending', 'Retry the original action. / أعد محاولة الإجراء الأصلي.', status=404)
    return result


@router.put('/{watch_id}')
def save(body: Command, request: Request, watch_id: str = Path(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9-]+$'),
         owner=Depends(actor)):
    return invoke(request, 'save', str(owner), str(owner), str(watch_id), body.model_dump())


@router.get('/{watch_id}')
def record(request: Request, watch_id: str = Path(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9-]+$'),
           owner=Depends(actor)):
    return invoke(request, 'record', str(owner), str(owner), watch_id)
