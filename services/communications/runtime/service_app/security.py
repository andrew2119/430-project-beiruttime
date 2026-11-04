"""Fresh principal checks; user-supplied actor headers are never authority."""
from fastapi import HTTPException, Request
from bt_bulkheads import Unavailable
from bt_runtime.principal import current_principal
from bt_contracts_core.errors import PublicError

async def actor(request: Request):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    try:
        principal = await current_principal(request.app.state.identity, token, request.state.request_id)
    except (ValueError, TypeError):
        raise HTTPException(503) from None
    if isinstance(principal, Unavailable):
        raise HTTPException(503)
    # Personal buyer resources cannot be read through a represented organization's session.
    if principal.actor.organization_id is not None:
        raise HTTPException(403)
    request.state.principal = principal
    return principal.actor.subject_id


def idempotency(request: Request):
    key = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(key) <= 128 or not all(c.isalnum() or c in '-_' for c in key):
        raise PublicError('idempotency_required', 'Supply a bounded Idempotency-Key.', status=400)
    return key
