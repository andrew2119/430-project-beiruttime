"""Private route boundary; runtime supplies authenticated context and providers."""
from fastapi import APIRouter, Depends, Request
from uuid import UUID
from pydantic import ValidationError

def router_for(service, principal, change_type):
    router = APIRouter()

    @router.get('/internal/v1/payout-recipients')
    async def current(actor=Depends(principal)):
        value = service.run(str(actor.actor_id), actor.subject_id, actor.organization_id, 'read')
        return envelope(value, actor)

    @router.get('/internal/v1/payout-recipients/operations/{operation_id}')
    async def lookup(operation_id: UUID, actor=Depends(principal)):
        value = service.run(str(actor.actor_id), actor.subject_id, actor.organization_id,
                            'lookup', operation_id=operation_id)
        return envelope(value, actor, operation_id)

    @router.post('/internal/v1/payout-recipients')
    async def change(request: Request, actor=Depends(principal)):
        # Bound bytes before parsing; no recipient body enters access logs.
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 2048:
                return envelope({'state':'denied','code':'request_too_large'}, actor)
        try:
            command = change_type.model_validate_json(body)
        except ValidationError:
            return envelope({'state':'denied','code':'invalid_request'}, actor)
        return envelope(service.run(str(actor.actor_id), actor.subject_id,
                        actor.organization_id, 'change', command), actor, command.operation_id)

    return router

def envelope(value, actor, operation_id=None):
    return {'schema_version':1, 'subject_id':str(actor.subject_id),
            'organization_id':str(actor.organization_id) if actor.organization_id else None,
            'operation_id':str(operation_id) if operation_id else None,
            'watch_id':None, 'actor_id':str(actor.actor_id), 'expected_revision':None,
            'pending_reason':None, 'next_actor':None, 'next_review_at':None,
            'state':'succeeded', 'revision':0, **value}
