import base64
import hashlib
import hmac
import os
import secrets
from uuid import UUID, uuid4
import asyncpg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from bt_runtime.app.auth import require_principal
from .security import (audit, check_password, cookie, digest, event, hash_password, limit, live_actor,
    DUMMY_PASSWORD_HASH, new_session, password_matches, password_work, private_key, projection, require_origin, session_response)

router = APIRouter()


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if value.count('@') != 1 or '.' not in value.split('@')[1] or any(c.isspace() for c in value):
            raise ValueError('Invalid email')
        return value


class Register(Credentials):
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator('display_name')
    @classmethod
    def name(cls, value):
        if not value.strip():
            raise ValueError('Enter a name')
        return value.strip()


class Recovery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)


class Reset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=12, max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class Reauthenticate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1,max_length=128)
    purpose: str = Field(pattern=r'^contact-change$')
    binding: str = Field(min_length=1,max_length=512)


async def admission(request, scope, maximum=12):
    # Counters commit independently even if a command is rejected.
    async with request.app.state.pool.acquire() as tx:
        await limit(tx, scope, maximum=maximum)


@router.post('/v1/accounts/register', status_code=201)
async def register(body: Register, request: Request, response: Response):
    require_origin(request)
    private_key()  # Configuration fails before durable registration.
    check_password(body.password)
    await admission(request, 'register:' + str(request.client.host), 30)
    encoded = await password_work(hash_password, body.password)
    raw_key = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(raw_key) <= 100:
        raise PublicError('operation_key_required', 'A request key is required.', status=422)
    key = digest('register:' + raw_key)
    payload_digest = hmac.new(private_key().encode(), body.model_dump_json().encode(), hashlib.sha256).hexdigest()
    async with unit_of_work(request.app.state.pool, lock_key='registration:' + body.email) as tx:
        prior = await tx.fetchrow('SELECT * FROM identity_account_operations WHERE key=$1', key)
        if prior and prior['digest'] != payload_digest:
            raise PublicError('operation_conflict', 'Use a new request key.', status=409)
        if prior:
            account = await tx.fetchrow('SELECT * FROM identity_accounts WHERE id=$1 FOR UPDATE', prior['subject_id'])
            if account['status'] != 'active' or not await password_work(password_matches, body.password, account['password_hash']):
                raise HTTPException(401)
        else:
            if await tx.fetchval('SELECT id FROM identity_accounts WHERE email=$1', body.email):
                raise PublicError('registration_unavailable', 'Sign in or use account recovery.', status=409)
            account = await tx.fetchrow('''INSERT INTO identity_accounts(id,email,display_name,password_hash)
                VALUES($1,$2,$3,$4) RETURNING *''', uuid4(), body.email, body.display_name, encoded)
            try:
                await tx.execute('INSERT INTO identity_account_operations VALUES($1,$2,$3)', key, payload_digest, account['id'])
            except asyncpg.UniqueViolationError:
                raise PublicError('operation_conflict', 'Use a new request key.', status=409) from None
            await audit(tx, request, account['id'], account['id'], 'account.register', 'accepted')
            await event(tx, request, account['id'], 'identity.account-registered.v1')
        result, refresh = await new_session(tx, request, account)
    cookie(response, refresh)
    return result


@router.post('/v1/accounts/login')
async def login(body: Credentials, request: Request, response: Response):
    require_origin(request)
    await admission(request, 'login-ip:' + str(request.client.host), 60)
    await admission(request, 'login-email:' + body.email)
    async with unit_of_work(request.app.state.pool, lock_key='account-login:' + body.email) as tx:
        account = await tx.fetchrow('SELECT * FROM identity_accounts WHERE email=$1 FOR UPDATE', body.email)
        # Same KDF path for unknown accounts, without creating an account.
        encoded = account['password_hash'] if account else DUMMY_PASSWORD_HASH
        valid = await password_work(password_matches, body.password, encoded)
        if not account or not valid or account['status'] != 'active':
            result, refresh = None, None
            await audit(tx, request, None, None, 'account.login', 'denied')
        else:
            if not account['password_hash'].startswith('scrypt$16384$8$5$'):
                upgraded = await password_work(hash_password,body.password)
                await tx.execute('UPDATE identity_accounts SET password_hash=$2 WHERE id=$1',account['id'],upgraded)
            result, refresh = await new_session(tx, request, account)
            await audit(tx, request, account['id'], account['id'], 'account.login', 'accepted')
    if result is None:
        raise PublicError('invalid_credentials', 'Sign in failed. Check your details or recover your account.', status=401)
    cookie(response, refresh)
    return result


async def refresh_owner(tx, request):
    raw = request.cookies.get('bt_refresh', '')
    if not 32 <= len(raw) <= 200:
        raise HTTPException(401)
    return await tx.fetchrow('''SELECT s.subject_id,t.session_id FROM identity_refresh_tokens t
        JOIN identity_sessions s ON s.id=t.session_id WHERE t.hash=$1''', digest(raw))


@router.post('/v1/accounts/refresh')
async def refresh(request: Request, response: Response):
    require_origin(request)
    async with unit_of_work(request.app.state.pool) as tx:
        owner = await refresh_owner(tx, request)
        if not owner:
            raise HTTPException(401)
        account = await tx.fetchrow('SELECT * FROM identity_accounts WHERE id=$1 FOR UPDATE', owner['subject_id'])
        session = await tx.fetchrow('SELECT * FROM identity_sessions WHERE id=$1', owner['session_id'])
        token = await tx.fetchrow('SELECT * FROM identity_refresh_tokens WHERE hash=$1', digest(request.cookies['bt_refresh']))
        active = await tx.fetchval('SELECT $1::timestamptz>now()', session['expires_at'])
        if token['consumed_at'] or session['revoked_at'] or account['status'] != 'active' or not active:
            await tx.execute('UPDATE identity_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE id=$1', session['id'])
            result, successor = None, None
        else:
            successor = secrets.token_urlsafe(48)
            await tx.execute('UPDATE identity_refresh_tokens SET consumed_at=now() WHERE hash=$1', token['hash'])
            await tx.execute('INSERT INTO identity_refresh_tokens(hash,session_id) VALUES($1,$2)', digest(successor), session['id'])
            result = await session_response(tx, request, account, session['id'], successor)
    if result is None:
        raise HTTPException(401)
    cookie(response, successor)
    return result


@router.post('/v1/accounts/logout')
async def logout(request: Request, response: Response):
    require_origin(request)
    async with unit_of_work(request.app.state.pool) as tx:
        owner = await refresh_owner(tx, request)
        if owner:
            await tx.fetchrow('SELECT id FROM identity_accounts WHERE id=$1 FOR UPDATE', owner['subject_id'])
            await tx.execute('UPDATE identity_sessions SET revoked_at=now() WHERE id=$1', owner['session_id'])
            await audit(tx, request, owner['subject_id'], owner['session_id'], 'session.logout', 'accepted')
    cookie(response, '', remove=True)
    return {'signed_out': True}


@router.get('/internal/v1/principal')
async def principal(request: Request, organization_id: UUID | None = None):
    async with unit_of_work(request.app.state.pool) as tx:
        account, session = await live_actor(tx, request)
        result = await projection(tx, account, session)
        if organization_id:
            if organization_id not in result.organizations:
                raise HTTPException(403)
            result.actor.organization_id = organization_id
        return result.model_dump(mode='json')


@router.get('/v1/accounts/me')
async def me(request: Request):
    async with unit_of_work(request.app.state.pool) as tx:
        account, session = await live_actor(tx, request)
        return {'id': str(account['id']), 'email': account['email'], 'display_name': account['display_name'],
            'principal': (await projection(tx, account, session)).model_dump(mode='json')}


@router.post('/v1/accounts/reauthenticate')
async def reauthenticate(body: Reauthenticate,request: Request):
    await admission(request,'reauth-ip:'+str(request.client.host),60)
    await admission(request,'reauth-subject:'+require_principal(request).subject,10)
    async with unit_of_work(request.app.state.pool) as tx:
        account, session = await live_actor(tx,request,lock=True)
        if not await password_work(password_matches,body.password,account['password_hash']):
            raise PublicError('invalid_credentials','Confirm your current password.',status=401)
        proof = secrets.token_urlsafe(48)
        binding_hash = digest(body.binding)
        await tx.execute('''UPDATE identity_reauth_proofs SET consumed_at=now() WHERE subject_id=$1
            AND session_id=$2 AND purpose=$3 AND consumed_at IS NULL''',account['id'],session,body.purpose)
        await tx.execute('''INSERT INTO identity_reauth_proofs(hash,subject_id,session_id,purpose,binding_hash,expires_at)
            VALUES($1,$2,$3,$4,$5,now()+interval '5 minutes')''',digest(proof),account['id'],session,body.purpose,binding_hash)
        await audit(tx,request,account['id'],account['id'],'password.reauthenticate','accepted')
    return {'proof':proof,'purpose':body.purpose,'binding_digest':binding_hash,'expires_in':300}


@router.post('/v1/accounts/password')
async def change_password(body: PasswordChange, request: Request):
    check_password(body.new_password)
    await admission(request, 'password:' + str(request.client.host), 20)
    await admission(request, 'password-subject:' + require_principal(request).subject, 10)
    encoded = await password_work(hash_password, body.new_password)
    async with unit_of_work(request.app.state.pool) as tx:
        account, _ = await live_actor(tx, request, lock=True)
        if not await password_work(password_matches, body.current_password, account['password_hash']):
            raise PublicError('invalid_credentials', 'Check your current password.', status=401)
        await tx.execute('UPDATE identity_accounts SET password_hash=$2,access_revision=access_revision+1 WHERE id=$1', account['id'], encoded)
        await tx.execute('UPDATE identity_sessions SET revoked_at=now() WHERE subject_id=$1', account['id'])
        await audit(tx, request, account['id'], account['id'], 'password.change', 'accepted')
        await event(tx, request, account['id'], 'identity.password-changed.v1')
    return {'sign_in_required': True}


@router.post('/v1/accounts/recovery', status_code=202)
async def recover(body: Recovery, request: Request):
    require_origin(request)
    await admission(request, 'recovery-ip:' + str(request.client.host), 30)
    # Per-address suppression stays generic and does not reveal account eligibility.
    async with request.app.state.pool.acquire() as tx:
        try:
            await limit(tx, 'recovery-email:' + body.email.lower().strip(), maximum=3)
        except PublicError:
            return {'accepted': True, 'delivery': 'simulated'}
    async with unit_of_work(request.app.state.pool) as tx:
        account = await tx.fetchrow('SELECT * FROM identity_accounts WHERE email=$1 FOR UPDATE', body.email.lower().strip())
        if account and account['status'] == 'active':
            raw = secrets.token_urlsafe(48)
            await tx.execute('UPDATE identity_password_resets SET consumed_at=now() WHERE subject_id=$1 AND consumed_at IS NULL', account['id'])
            await tx.execute("INSERT INTO identity_password_resets(hash,subject_id,expires_at) VALUES($1,$2,now()+interval '20 minutes')", digest(raw), account['id'])
            # A local-only encrypted mail capture is not token persistence in the reset ledger.
            nonce = secrets.token_bytes(12)
            cipher = AESGCM(hashlib.sha256(private_key().encode()).digest()).encrypt(nonce, raw.encode(), str(account['id']).encode())
            await tx.execute('INSERT INTO identity_demo_mail(id,subject_id,ciphertext) VALUES($1,$2,$3)', uuid4(), account['id'], base64.b64encode(nonce+cipher).decode())
            await event(tx, request, account['id'], 'identity.recovery-requested.v1')
    return {'accepted': True, 'delivery': 'simulated'}


@router.get('/internal/v1/accounts/demo-mail')
async def captured_mail(request: Request):
    # Explicit mailbox capability, not a generic operator bypass or public recovery response.
    async with unit_of_work(request.app.state.pool) as tx:
        account, session = await live_actor(tx, request, lock=True)
        principal = await projection(tx, account, session)
        if 'identity.demo-mail.read' not in principal.permissions:
            raise HTTPException(403)
        rows = await tx.fetch('SELECT * FROM identity_demo_mail ORDER BY created_at DESC LIMIT 20')
        active = await tx.fetch('''SELECT hash,subject_id FROM identity_password_resets WHERE consumed_at IS NULL
            AND expires_at>now() AND subject_id=ANY($1::uuid[])''', [row['subject_id'] for row in rows])
        valid = {(row['hash'],row['subject_id']) for row in active}
        messages = []
        cipher = AESGCM(hashlib.sha256(private_key().encode()).digest())
        origin = os.environ.get('BT_WEB_ORIGIN','http://localhost:3000').rstrip('/')
        for row in rows:
            sealed = base64.b64decode(row['ciphertext'])
            raw = cipher.decrypt(sealed[:12],sealed[12:],str(row['subject_id']).encode()).decode()
            if (digest(raw),row['subject_id']) in valid:
                messages.append({'id':str(row['id']),'recipient_id':str(row['subject_id']),
                    'recovery_link':origin+'/en/account?mode=reset#'+raw,'delivery':'simulated'})
        await audit(tx,request,account['id'],account['id'],'demo-mail.read','accepted')
    return {'messages':messages}


@router.post('/v1/accounts/reset')
async def reset(body: Reset, request: Request):
    require_origin(request)
    check_password(body.password)
    await admission(request, 'reset:' + str(request.client.host), 30)
    encoded = await password_work(hash_password, body.password)
    async with unit_of_work(request.app.state.pool) as tx:
        token = await tx.fetchrow('SELECT * FROM identity_password_resets WHERE hash=$1', digest(body.token))
        if not token:
            raise PublicError('invalid_reset', 'Request a new recovery link.', status=400)
        await tx.fetchrow('SELECT id FROM identity_accounts WHERE id=$1 FOR UPDATE', token['subject_id'])
        accepted = await tx.fetchval('''UPDATE identity_password_resets SET consumed_at=now()
            WHERE hash=$1 AND consumed_at IS NULL AND expires_at>now() RETURNING subject_id''', digest(body.token))
        if not accepted:
            raise PublicError('invalid_reset', 'Request a new recovery link.', status=400)
        await tx.execute('UPDATE identity_accounts SET password_hash=$2,access_revision=access_revision+1 WHERE id=$1', accepted, encoded)
        await tx.execute('UPDATE identity_sessions SET revoked_at=now() WHERE subject_id=$1', accepted)
        await audit(tx, request, accepted, accepted, 'password.reset', 'accepted')
        await event(tx, request, accepted, 'identity.password-changed.v1')
    return {'sign_in_required': True}
