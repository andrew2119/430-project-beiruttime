"""Closed service-to-service authority; a user token is never a machine grant."""
import jwt
from fastapi import HTTPException
from bt_contracts_core.errors import AccessDenied, PublicError


def service(request, allowed):
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise PublicError('service_auth_unavailable', 'Service authorization is unavailable.', status=503)
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    try:
        claims = jwt.decode(token, settings.service_auth_public_key, algorithms=['RS256'], audience='auction',
            issuer=settings.auth_issuer, options={'require': ['sub', 'type', 'iss', 'aud', 'iat', 'exp']})
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    if claims['type'] != 'service' or claims['sub'] not in allowed:
        raise AccessDenied('Wrong calling service')
    return claims['sub']
