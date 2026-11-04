from fastapi import HTTPException, Request
from bt_runtime.auth import InvalidToken, Principal, TokenVerifier


def require_principal(request: Request) -> Principal:
    settings = request.app.state.settings
    if not settings.auth_public_key:
        raise HTTPException(503)
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(401)
    try:
        return TokenVerifier(settings.auth_public_key, settings.auth_issuer, settings.auth_audience).verify(token)
    except InvalidToken:
        raise HTTPException(401) from None
