import os
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied
from bt_runtime.app.auth import require_principal
from bt_runtime.principal import current_principal
from .composition import compose

router = APIRouter(prefix='/v1/buyer-workspace', tags=['buyer-workspace'])


def clients(app):
    if not hasattr(app.state, 'l06_workspace_clients'):
        app.state.l06_workspace_clients = {
            name: DependencyClient(name, os.environ.get(name.upper() + '_API_URL', default),
                                   # Fresh identity + parallel sources must finish
                                   # inside the gateway's 1.2s service deadline.
                                   timeout=.3 if name == 'identity' else .6, concurrency=4)
            for name, default in [('identity', 'http://identity:8000'),
                                  ('auction', 'http://auction:8000'), ('orders', 'http://orders:8000')]
        }
    return app.state.l06_workspace_clients


async def close_clients(app, stop):
    # Lifespan-owned pools, never an unbounded pool per request.
    clients(app)
    try:
        await stop.wait()
    finally:
        for client in app.state.l06_workspace_clients.values():
            await client.aclose()


@router.get('')
async def workspace(request: Request, verified=Depends(require_principal)):
    upstreams = clients(request.app)
    token = request.headers['authorization'].partition(' ')[2]
    try:
        principal = await current_principal(upstreams['identity'], token, request.state.request_id)
    except ValueError:
        # A 200 with malformed principal data is unavailable, never authority.
        raise HTTPException(503) from None
    if isinstance(principal, Unavailable):
        raise HTTPException(503)
    if (str(principal.actor.subject_id) != verified.subject or
            principal.actor.session_id != verified.session_id or 'buyer' not in principal.roles):
        raise AccessDenied('Buyer session required')
    return await compose(principal.actor.subject_id, token, request.state.request_id,
                         upstreams['auction'], upstreams['orders'])
