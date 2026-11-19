"""Route factory, intentionally not registered with the shared runtime."""
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from .model import Refused


def router_for(boundary, store_factory, current_context):
    router = APIRouter(prefix='/v1/transaction-reviews')

    async def mutate(kind, subject_id, body, context):
        if body.get('kind') != kind or body.get('subject_id') != subject_id:
            raise HTTPException(422, detail='invalid_binding')
        return await boundary.execute(body, context['actor_id'], context['organization_id'])

    @router.post('/purchases/{subject_id}')
    async def create(subject_id: str, body: dict = Body(...), context=Depends(current_context)):
        return await mutate('create', subject_id, body, context)

    @router.post('/{subject_id}/reply')
    async def reply(subject_id: str, body: dict = Body(...), context=Depends(current_context)):
        return await mutate('reply', subject_id, body, context)

    @router.post('/{subject_id}/reports')
    async def report(subject_id: str, body: dict = Body(...), context=Depends(current_context)):
        return await mutate('report', subject_id, body, context)

    @router.post('/{subject_id}/decisions')
    async def decide(subject_id: str, body: dict = Body(...), context=Depends(current_context)):
        return await mutate('decide', subject_id, body, context)

    @router.get('/operations/{operation_id}')
    def lookup(operation_id: str, subject_id: str, context=Depends(current_context)):
        store = store_factory()
        try:
            return store.lookup(operation_id, context['actor_id'], context['organization_id'], subject_id)
        except Refused:
            raise HTTPException(403, detail='scope_denied') from None
        finally:
            store.db.close()

    @router.get('/sellers/{seller_id}')
    def public(seller_id: str, page: int = Query(1, ge=1)):
        if len(seller_id) > 128:
            raise HTTPException(422, detail='invalid_reference')
        store = store_factory()
        try:
            return store.public(seller_id, page)
        finally:
            store.db.close()

    return router
