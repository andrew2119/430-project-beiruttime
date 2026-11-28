from typing import Literal
import os
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied
from bt_runtime.app.auth import require_principal
from bt_runtime.principal import current_principal
from .composition import ActivityAccessDenied, StaleActivityCursor, compose, compose_current, compose_reservations

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


ActivityView = Query(default=None, pattern='^(leading|outbid|calendar|won|lost|no_sale|unpaid|released)$')
ActivityCursor = Query(default=None, max_length=200)


async def buyer_context(request, verified):
    upstreams = clients(request.app)
    token = request.headers['authorization'].partition(' ')[2]
    try:
        principal = await current_principal(upstreams['identity'], token, request.state.request_id)
    except ValueError:
        raise HTTPException(503) from None
    if isinstance(principal, Unavailable):
        raise HTTPException(503)
    if (str(principal.actor.subject_id) != verified.subject or
            principal.actor.session_id != verified.session_id or principal.actor.organization_id is not None or
            'buyer' not in principal.roles):
        raise AccessDenied('Buyer session required')
    return principal.actor.subject_id, token, request.state.request_id, upstreams


@router.get('')
async def workspace(request: Request, view: str | None = ActivityView,
                    cursor: str | None = ActivityCursor, section: Literal['reservations'] | None = None,
                    verified=Depends(require_principal)):
    context = await buyer_context(request, verified)
    if section == 'reservations':
        if view is not None:
            raise HTTPException(422)
        try:
            reservation_cursor = UUID(cursor) if cursor is not None else None
        except ValueError:
            raise HTTPException(422) from None
        owner, token, request_id, upstreams = context
        page = await compose_reservations(owner, token, request_id, upstreams['orders'], cursor=reservation_cursor)
        return JSONResponse(page, headers={'Cache-Control': 'no-store'})
    if view is not None:
        return await activity_response(context, view, cursor)
    owner, token, request_id, upstreams = context
    return await compose(owner, token, request_id, upstreams['auction'], upstreams['orders'])


@router.get('/v2')
async def current_workspace(request: Request,
                            view: str = Query(default='leading', pattern='^(leading|outbid|calendar|won|lost|no_sale|unpaid|released)$'),
                            cursor: str | None = Query(default=None, max_length=200),
                            verified=Depends(require_principal)):
    return await activity_response(await buyer_context(request, verified), view, cursor)


async def activity_response(context, view, cursor):
    owner, token, request_id, upstreams = context
    headers = {'Cache-Control': 'no-store'}
    try:
        page = await compose_current(owner, token, request_id,
                                     upstreams['auction'], view=view, cursor=cursor)
    except ActivityAccessDenied:
        return JSONResponse({'error': {'code': 'auction_access_denied', 'message': 'Auction access denied.',
                                       'request_id': request_id, 'details': {}}},
                            status_code=403, headers=headers)
    except StaleActivityCursor:
        return JSONResponse({'error': {'code': 'stale_cursor', 'message': 'Activity changed.',
                                       'request_id': request_id, 'details': {}}},
                            status_code=409, headers=headers)
    # Preserve the verified partial answer through the gateway's upstream failure handling.
    return JSONResponse(page, headers=headers)
