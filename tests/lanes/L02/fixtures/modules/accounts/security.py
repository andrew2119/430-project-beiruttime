"""CP S-02/S-04/S-05: account-serialized lineage and hash-only purpose tokens."""
import asyncio
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import urlsplit
import jwt
from fastapi import HTTPException, Request
from bt_contracts_core.models import Actor, EventEnvelope
from bt_contracts_core.errors import PublicError
from bt_events import enqueue
from service_app.identity import live_actor as live_actor
from bt_runtime.principal import CurrentPrincipal, OrganizationGrant

hash_slots = asyncio.Semaphore(2)
# One verification KDF for unknown and known recipients; this value grants no identity.
DUMMY_PASSWORD_HASH = 'scrypt$AAAAAAAAAAAAAAAAAAAAAA==$+RF4mCDRd3vqijnTN1XYGJ7Ugd+50DsEb4BfXrVOdQ0='


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def private_key() -> str:
    key = os.environ.get('BT_AUTH_PRIVATE_KEY', '')
    if not key:
        raise HTTPException(503)
    return key.replace('\\n', '\n')


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return 'scrypt$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(value).decode()


def password_matches(password: str, encoded: str) -> bool:
    try:
        _, salt, _ = encoded.split('$')
        return hmac.compare_digest(hash_password(password, base64.b64decode(salt)), encoded)
    except (ValueError, TypeError):
        return False


async def password_work(callback, *args):
    # Bound allocations before running memory-hard work off the event loop.
    if hash_slots.locked():
        raise PublicError('try_later', 'Try again shortly.', status=429)
    async with hash_slots:
        return await asyncio.to_thread(callback, *args)


def check_password(value: str):
    if not 12 <= len(value) <= 128 or value.lower() in {'password12345', 'beiruttime123', '123456789012'}:
        raise PublicError('weak_password', 'Use a unique password of 12 to 128 characters.', status=422)


def require_origin(request: Request):
    configured = os.environ.get('BT_ALLOWED_WEB_ORIGINS') or os.environ.get('BT_WEB_ORIGIN', 'http://localhost:3000')
    allowed = {value.strip().rstrip('/') for value in configured.split(',') if value.strip()}
    if not allowed or len(allowed) > 32 or len(configured) > 4096:
        raise HTTPException(503)
    for origin in allowed:
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError:
            raise HTTPException(503) from None
        if '*' in origin or parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or (port is not None and port < 1):
            raise HTTPException(503)
    if request.headers.get('origin') not in allowed:
        raise HTTPException(403)


def cookie(response, token: str, *, remove=False):
    options = dict(key='bt_refresh', path='/', httponly=True, secure=os.environ.get('BT_LOCAL_HTTP') != '1', samesite='strict')
    if remove:
        response.delete_cookie(**options)
    else:
        response.set_cookie(value=token, max_age=7 * 24 * 3600, **options)


async def limit(tx, scope: str, *, maximum=12, seconds=900):
    count = await tx.fetchval('''INSERT INTO identity_auth_limits(scope,attempts,resets_at)
        VALUES($1,1,now()+$2*interval '1 second') ON CONFLICT(scope) DO UPDATE
        SET attempts=CASE WHEN identity_auth_limits.resets_at<=now() THEN 1 ELSE identity_auth_limits.attempts+1 END,
        resets_at=CASE WHEN identity_auth_limits.resets_at<=now() THEN excluded.resets_at ELSE identity_auth_limits.resets_at END
        RETURNING attempts''', digest(scope), seconds)
    if count > maximum:
        raise PublicError('try_later', 'Try again later.', status=429)


async def audit(tx, request, actor, resource, action, outcome):
    await tx.execute('INSERT INTO identity_security_audit VALUES($1,$2,$3,$4,$5,$6,now())',
        uuid4(), actor, resource, action, outcome, request.state.request_id)


async def event(tx, request, subject, kind):
    await enqueue(tx, EventEnvelope(type=kind, source='identity', subject=str(subject),
        request_id=request.state.request_id, data={'subject_id': str(subject)}), ['communications'])


async def projection(tx, account, session):
    grants = await tx.fetch('SELECT * FROM identity_access_grants WHERE subject_id=$1 AND revoked_at IS NULL', account['id'])
    roles, permissions, orgs = {'buyer'}, set(), {}
    for grant in grants:
        if grant['organization_id'] is None:
            roles.add(grant['role'])
            permissions.update(grant['permissions'])
        else:
            item = orgs.setdefault(grant['organization_id'], {'roles': set(), 'permissions': set()})
            item['roles'].add(grant['role'])
            item['permissions'].update(grant['permissions'])
            roles.add(grant['role'])
    return CurrentPrincipal(actor=Actor(subject_id=account['id'], session_id=str(session)),
        roles=sorted(roles), permissions=sorted(permissions), organizations=list(orgs),
        organization_grants=[OrganizationGrant(organization_id=key, roles=sorted(value['roles']), permissions=sorted(value['permissions'])) for key,value in orgs.items()])


async def session_response(tx, request, account, session, refresh):
    now = datetime.now(timezone.utc)
    token = jwt.encode({'iss': request.app.state.settings.auth_issuer, 'aud': request.app.state.settings.auth_audience,
        'sub': str(account['id']), 'sid': str(session), 'iat': now, 'exp': now + timedelta(minutes=5), 'type': 'access'}, private_key(), algorithm='RS256')
    principal = await projection(tx, account, session)
    return {'access_token': token, 'token_type': 'Bearer', 'expires_in': 300,
        'account': {'id': str(account['id']), 'email': account['email'], 'display_name': account['display_name']},
        'principal': principal.model_dump(mode='json'),
        'access_fingerprint': digest(f"{account['id']}:{session}:{account['access_revision']}:{principal.model_dump_json()}")}


async def new_session(tx, request, account):
    session, refresh = uuid4(), secrets.token_urlsafe(48)
    await tx.execute('''INSERT INTO identity_sessions(id,subject_id,expires_at) VALUES($1,$2,now()+interval '7 days')''', session, account['id'])
    await tx.execute('INSERT INTO identity_refresh_tokens(hash,session_id) VALUES($1,$2)', digest(refresh), session)
    # Bounded active session families; all issuance shares the account lock.
    await tx.execute('''UPDATE identity_sessions SET revoked_at=now() WHERE subject_id=$1 AND id IN
        (SELECT id FROM identity_sessions WHERE subject_id=$1 AND revoked_at IS NULL ORDER BY created_at DESC OFFSET 5)''', account['id'])
    return await session_response(tx, request, account, session, refresh), refresh
