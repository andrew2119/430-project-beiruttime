"""Additive route factory; composition supplies authenticated private dependencies."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from bt_contracts.pricing.counteroffers.current import Command


def router_for(service, principal_dependency):
    router = APIRouter(prefix='/v1/counteroffers', tags=['counteroffers'])

    @router.post('/{subject_id}/commands')
    async def command(subject_id: UUID, body: Command, principal=Depends(principal_dependency)):
        if (body.subject_id != subject_id or body.actor_id != principal.actor_id
                or body.organization_id != principal.organization_id):
            raise HTTPException(status_code=403, detail={'code': 'denied'})
        return await service.command(body)

    @router.get('/{subject_id}/operations/{operation_id}')
    async def operation(subject_id: UUID, operation_id: UUID, principal=Depends(principal_dependency)):
        try:
            return await service.operation(principal, subject_id, operation_id)
        except PermissionError:
            raise HTTPException(status_code=403, detail={'code': 'denied'}) from None
        except (TimeoutError, ConnectionError):
            raise HTTPException(status_code=503, detail={'code': 'retry_same_operation'}) from None

    @router.get('/{subject_id}')
    async def current(subject_id: UUID, principal=Depends(principal_dependency)):
        try:
            return await service.current(principal, subject_id)
        except PermissionError:
            raise HTTPException(status_code=403, detail={'code': 'denied'}) from None
        except (TimeoutError, ConnectionError):
            raise HTTPException(status_code=503, detail={'code': 'unavailable'}) from None

    return router
