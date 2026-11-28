"""Composition factory; the runtime supplies current access and source providers."""
from fastapi import APIRouter, Header, HTTPException, Query, Response
from .projection import Denied, Unavailable


def create_router(service):
    router = APIRouter(prefix='/v1/order-timeline', tags=['order-timeline'])

    async def invoke(response, authorization, action, *args):
        response.headers['Cache-Control'] = 'private, no-store'
        if not authorization or not authorization.startswith('Bearer '):
            raise HTTPException(401, detail='unauthenticated', headers={'Cache-Control': 'no-store'})
        try:
            return await action(authorization, *args)
        except (Denied, Unavailable, ValueError) as error:
            status, code = (403, 'denied') if isinstance(error, Denied) else (503, 'unavailable') if isinstance(error, Unavailable) else (422, 'invalid')
            raise HTTPException(status, detail=code, headers={'Cache-Control': 'no-store'}) from None

    @router.get('')
    async def catalog(response: Response, authorization: str | None = Header(default=None),
                      organization_id: str | None = Query(default=None, max_length=96),
                      offset: int = Query(default=0, ge=0, le=1000000), limit: int = Query(default=20, ge=1, le=20)):
        return await invoke(response, authorization, service.list, organization_id, offset, limit)

    @router.get('/{order_id}')
    async def detail(order_id: str, response: Response, authorization: str | None = Header(default=None),
                     organization_id: str | None = Query(default=None, max_length=96)):
        return await invoke(response, authorization, service.read, order_id, organization_id)

    return router
