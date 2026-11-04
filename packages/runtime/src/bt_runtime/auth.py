"""CP S-01: cryptographic identity is not resource authorization.

Domain handlers must separately check current permissions, ownership and revocation.
Verification keys are explicit (no caller-controlled JWKS URL or algorithm choice).
"""
from dataclasses import dataclass
import jwt


class InvalidToken(ValueError):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    session_id: str
    issuer: str
    audience: str


class TokenVerifier:
    def __init__(self, public_key: str, issuer: str, audience: str):
        if not public_key or not issuer or not audience:
            raise ValueError('Token verification must be explicitly configured')
        self.public_key, self.issuer, self.audience = public_key, issuer, audience

    def verify(self, token: str) -> Principal:
        if len(token) > 8192:
            raise InvalidToken('Invalid access token')
        try:
            claims = jwt.decode(token, self.public_key, algorithms=['RS256'],
                issuer=self.issuer, audience=self.audience,
                options={'require': ['exp', 'iat', 'sub', 'sid', 'iss', 'aud', 'type']}, leeway=5)
            if claims['type'] != 'access' or not isinstance(claims['sub'], str) or not claims['sub'] \
                    or not isinstance(claims['sid'], str) or not claims['sid']:
                raise InvalidToken('Invalid access token')
            return Principal(claims['sub'], claims['sid'], self.issuer, self.audience)
        except jwt.InvalidTokenError as exc:
            raise InvalidToken('Invalid access token') from exc
