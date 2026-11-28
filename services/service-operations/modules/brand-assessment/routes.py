"""Composition supplies authenticated identity and the current-provider store."""
from fastapi import APIRouter, Depends, HTTPException


def router_for(store, command_type, current_identity):
    router = APIRouter(prefix='/v1/brand-assessments')

    def invoke(call):
        try:
            return call()
        except Exception as error:
            if type(error).__name__ != 'Rejected':
                raise
            code = str(error)
            raise HTTPException(status_code=503 if code == 'unavailable' else 403 if code == 'denied' else 409,
                                detail={'code': code}) from None

    async def command(subject_id: str, body: command_type, identity=Depends(current_identity)):
        if (body.subject_id != subject_id or body.actor_id != identity.actor_id
                or body.organization_id != identity.organization_id):
            raise HTTPException(403, detail={'code': 'denied'})
        return invoke(lambda: store.command(body))

    @router.get('/{subject_id}')
    async def read(subject_id: str, identity=Depends(current_identity)):
        return invoke(lambda: store.read(identity.actor_id, identity.organization_id, subject_id))

    @router.get('/{subject_id}/operations/{operation_id}')
    async def operation(subject_id: str, operation_id: str, identity=Depends(current_identity)):
        result = invoke(lambda: store.lookup(identity.actor_id, identity.organization_id, subject_id, operation_id))
        if result is None:
            raise HTTPException(404, detail={'code': 'not_found'})
        return result

    router.add_api_route('/{subject_id}/commands', command, methods=['POST'])
    return router
