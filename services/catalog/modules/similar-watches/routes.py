"""Additive route factory; the catalog composition owns mounting."""
from fastapi import APIRouter, HTTPException, Request
from .service import Query, Result, find


def create_router(provider_for_request):
    router = APIRouter(prefix='/v1/similar-watches')

    @router.get('/{subject_id}', response_model=Result)
    async def read(subject_id: str, request: Request):
        # Closed query parsing rejects identity, organization and private filters.
        values = dict(request.query_params)
        if len(request.url.query) > 512 or set(values) - {'operation_id', 'expected_revision', 'offset'} or len(values) != len(request.query_params.multi_items()):
            raise HTTPException(422, detail='Duplicate parameters / معلمات مكررة')
        try:
            query = Query.model_validate({**values, 'subject_id': subject_id}, strict=False)
            # Integer query strings are accepted; decimal and boolean values are not.
            for name in ('expected_revision', 'offset'):
                if name in values and not (values[name].isascii() and values[name].isdigit()):
                    raise ValueError('Invalid integer')
        except ValueError:
            raise HTTPException(422, detail='Check the request / تحقق من الطلب') from None
        return await find(provider_for_request(request), query)

    return router
