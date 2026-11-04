import os
from fastapi import HTTPException, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_runtime.principal import current_principal


def clients(app):
    if not hasattr(app.state, 'moderation_clients'):
        app.state.moderation_clients = {name: DependencyClient(name, os.getenv('BT_'+name.upper()+'_URL', 'http://'+name+':8000'), timeout=1.2, concurrency=4)
            for name in ('identity', 'catalog', 'communications')}
    return app.state.moderation_clients


def bearer(request):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token)>8192:
        raise HTTPException(401)
    return token


async def principal(request: Request):
    try:
        result = await current_principal(clients(request.app)['identity'], bearer(request), request.state.request_id)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503) from None
    if isinstance(result, Unavailable):
        raise HTTPException(503)
    return result
