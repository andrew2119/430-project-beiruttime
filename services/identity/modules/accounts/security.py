"""Account-serialized lineage and hash-only purpose tokens."""
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
from service_app.session_slots import link_until, refresh_cookie_name
from bt_runtime.principal import CurrentPrincipal, OrganizationGrant

hash_slots = asyncio.Semaphore(2)
# One verification KDF for unknown and known recipients; this value grants no identity.
DUMMY_PASSWORD_HASH = 'scrypt$16384$8$5$AAAAAAAAAAAAAAAAAAAAAA==$+/fpavYGsDiOiBCZChyFGxxutVCG281aiPQJ1W3Ot24='


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def private_key() -> str:
    key = os.environ.get('BT_AUTH_PRIVATE_KEY', '')
    if not key:
        raise HTTPException(503)
    return key.replace('\\n', '\n')


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    # The 16 MiB/p=5 profile keeps two concurrent verifications inside the runtime budget.
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=5, dklen=32)
    return 'scrypt$16384$8$5$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(value).decode()


def password_matches(password: str, encoded: str) -> bool:
    try:
        parts = encoded.split('$')
        if len(parts) == 3 and parts[0] == 'scrypt':
            _, salt, expected = parts
            parallelism = 1  # Read-only compatibility; successful login upgrades this profile.
        elif len(parts) == 6 and parts[:4] == ['scrypt','16384','8','5']:
            _, _, _, _, salt, expected = parts
            parallelism = 5
        else:
            return False
        value = hashlib.scrypt(password.encode(),salt=base64.b64decode(salt,validate=True),n=16384,r=8,p=parallelism,dklen=32)
        return hmac.compare_digest(value,base64.b64decode(expected,validate=True))
    except (ValueError, TypeError):
        return False


async def password_work(callback, *args):
    # Cancellation must not free capacity while its blocking KDF still owns memory.
    if hash_slots.locked():
        raise PublicError('try_later', 'Try again shortly.', status=429)
    await hash_slots.acquire()
    task = asyncio.create_task(asyncio.to_thread(callback,*args))
    def completed(result):
        hash_slots.release()
        if not result.cancelled():
            result.exception()
    task.add_done_callback(completed)
    return await asyncio.shield(task)


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


def cookie(response, token: str, *, remove=False, slot: str | None = None):
    options = dict(key=refresh_cookie_name(slot), path='/', httponly=True, secure=os.environ.get('BT_LOCAL_HTTP') != '1', samesite='strict')
    if remove:
        response.delete_cookie(**options)
    else:
        # A slot cookie has no lifetime of its own, so it ends with the browser session.
        response.set_cookie(value=token, max_age=None if slot else 7 * 24 * 3600, **options)


async def attempts(tx, scope: str, *, seconds=900) -> int:
    """Count one attempt in scope's window and return how many the window holds now."""
    return await tx.fetchval('''INSERT INTO identity_auth_limits(scope,attempts,resets_at)
        VALUES($1,1,now()+$2*interval '1 second') ON CONFLICT(scope) DO UPDATE
        SET attempts=CASE WHEN identity_auth_limits.resets_at<=now() THEN 1 ELSE identity_auth_limits.attempts+1 END,
        resets_at=CASE WHEN identity_auth_limits.resets_at<=now() THEN excluded.resets_at ELSE identity_auth_limits.resets_at END
        RETURNING attempts''', digest(scope), seconds)


async def limit(tx, scope: str, *, maximum=12, seconds=900):
    if await attempts(tx, scope, seconds=seconds) > maximum:
        raise PublicError('try_later', 'Try again later.', status=429)


async def audit(tx, request, actor, resource, action, outcome):
    await tx.execute('INSERT INTO identity_security_audit VALUES($1,$2,$3,$4,$5,$6,now())',
        uuid4(), actor, resource, action, outcome, request.state.request_id)


async def event(tx, request, subject, kind):
    await enqueue(tx, EventEnvelope(type=kind, source='identity', subject=str(subject),
        request_id=request.state.request_id, data={'subject_id': str(subject)}), ['communications'])


async def projection(tx, account, session):
    grants = await tx.fetch('SELECT * FROM identity_access_grants WHERE subject_id=$1 AND revoked_at IS NULL ORDER BY organization_id,role,id', account['id'])
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


async def session_response(tx, request, account, session, refresh, *, until=None):
    now = datetime.now(timezone.utc)
    # A link session's access token never outlives the session's own end time.
    expires = now + timedelta(minutes=5) if until is None else min(now + timedelta(minutes=5), until)
    token = jwt.encode({'iss': request.app.state.settings.auth_issuer, 'aud': request.app.state.settings.auth_audience,
        'sub': str(account['id']), 'sid': str(session), 'iat': now, 'exp': expires, 'type': 'access'}, private_key(), algorithm='RS256')
    principal = await projection(tx, account, session)
    return {'access_token': token, 'token_type': 'Bearer', 'expires_in': max(0, int((expires - now).total_seconds())),
        'account': {'id': str(account['id']), 'email': account['email'], 'display_name': account['display_name']},
        'principal': principal.model_dump(mode='json'),
        'access_fingerprint': digest(f"{account['id']}:{session}:{account['access_revision']}:{principal.model_dump_json()}")}


async def new_session(tx, request, account, *, demo=None):
    """A new session family; demo=(role, switch) makes it a link session of that activation."""
    session, refresh = uuid4(), secrets.token_urlsafe(48)
    await tx.execute('''INSERT INTO identity_sessions(id,subject_id,expires_at) VALUES($1,$2,now()+interval '7 days')''', session, account['id'])
    until = None
    if demo is not None:
        role, switch = demo
        # A link session ends with the switch, and the Operator link's no later than its cutoff.
        until = link_until(role, switch)
        await tx.execute('UPDATE identity_sessions SET expires_at=least(expires_at,$2) WHERE id=$1', session, until)
        await tx.execute('INSERT INTO identity_demo_sessions(session_id,role,activation) VALUES($1,$2,$3)', session, role, switch.activation)
    await tx.execute('INSERT INTO identity_refresh_tokens(hash,session_id) VALUES($1,$2)', digest(refresh), session)
    # Bounded active session families per kind; all issuance shares the account lock, and
    # link sessions never displace the account's ordinary sessions, nor the reverse.
    kind = 'EXISTS' if demo is not None else 'NOT EXISTS'
    await tx.execute(f'''UPDATE identity_sessions SET revoked_at=now() WHERE subject_id=$1 AND id IN
        (SELECT s.id FROM identity_sessions s WHERE s.subject_id=$1 AND s.revoked_at IS NULL
         AND {kind}(SELECT 1 FROM identity_demo_sessions d WHERE d.session_id=s.id)
         ORDER BY s.created_at DESC OFFSET 5)''', account['id'])
    return await session_response(tx, request, account, session, refresh, until=until), refresh
