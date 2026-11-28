"""Per-tab session slots and switch-gated sample-account entry.

Every key, switch value, password and sample list here is made at run time; nothing in this file
can turn sample entry on anywhere else. The sample accounts are inserted the way the deploy seed
inserts them, at the seed's own pinned id and address with a password nobody knows, and entered in
the seed's ownership record (demo_seed_rows) by the database owner in the same transaction, because
public registration can never make one. In a build without the seed's ownership check
(bt_runtime.demo_seed.account_owner, seed round 4) a stand-in answers it from what each test
seeded, and the cases that need the seed's real record skip. The Operator link's account is a
stand-in registered here and made the first platform operator on this test's own throwaway
database, never the demo environment's own operator account or any of its values. The
Operator link's fixed cutoff is moved to a few hours ahead for each test, so these tests mean
the same on any date; test_session_slot_rules.py pins its real value.
"""
import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4
import asyncpg
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from bt_runtime.app import db
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from service_app import bootstrap_operator, session_slots
from service_app.main import create_app

try:
    from bt_runtime import demo_seed
except ImportError:  # a build without the deploy seed
    demo_seed = None

OWNER_CHECK = getattr(demo_seed, 'account_owner', None)
needs_seed = pytest.mark.skipif(OWNER_CHECK is None, reason="needs the deploy seed's own ownership check (seed round 4)")
ORIGIN = {'Origin': 'http://localhost:3000'}
PASSWORD = secrets.token_urlsafe(24)
# The seed's own address pattern, <role>.<set>@example.test.
BUYER, STAFF, OPERATOR = 'buyer.demo@example.test', 'staff.demo@example.test', 'operator.demo@example.test'
OUTSIDER = 'other@example.test'  # an address the existing account tests already use
# Made-up stand-ins for the demo environment's own operator account, which the repository never names.
STANDIN = 'operator-standin@example.test'
SECOND_STANDIN = 'second-standin@example.test'
STANDIN_REASON = 'Stand-in operator for the Operator link tests'
TABLES = ('identity_sessions', 'identity_demo_sessions', 'identity_demo_activations', 'identity_security_audit', 'identity_auth_limits')


@pytest.fixture
def keys(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setenv('BT_AUTH_PRIVATE_KEY', private)
    monkeypatch.setenv('BT_LOCAL_HTTP', '1')
    monkeypatch.setenv('BT_WEB_ORIGIN', 'http://localhost:3000')
    for name in ('BT_ALLOWED_WEB_ORIGINS', 'BT_EVENT_PRIVATE_KEY', 'BT_DEMO_ENTRY_UNTIL', 'BT_DEMO_ENTRY_KEY_SHA256', session_slots.OPERATOR_SETTING):
        monkeypatch.delenv(name, raising=False)
    return private, public


@pytest.fixture
def sample(monkeypatch):
    """The sample list for one test, filled by seeded(); it starts empty, as it ships."""
    listed = {}
    monkeypatch.setattr(session_slots, 'sample_list', lambda: tuple(listed.values()))
    return listed


@pytest.fixture
def cutoff(monkeypatch):
    """The Operator link's cutoff for one test: three hours ahead, past the default end time; a test may move it."""
    monkeypatch.setattr(session_slots, 'OPERATOR_LINK_CUTOFF', datetime.now(timezone.utc) + timedelta(hours=3))


@pytest.fixture
def ownership(monkeypatch):
    """The seed's ownership answers by set and role, for a build without the seed's own check.

    With the seed's check (seed round 4) the answers come from its real record and this stays empty.
    """
    answers = {}
    if OWNER_CHECK is None:
        async def check(tx, sample_set, role):
            if sample_set not in session_slots.SETS or role not in session_slots.LISTED_ROLES:
                raise ValueError('Not a sample sign-in account')
            return answers.get((sample_set, role), 'missing')
        monkeypatch.setattr(session_slots, 'demo_seed', SimpleNamespace(account_owner=check))
    return answers


@pytest_asyncio.fixture
async def environment(database_url, database_owner_url, keys, sample, ownership, cutoff):
    settings = Settings(database_url=database_url, service_name='identity', auth_public_key=keys[1])
    app = create_app(settings)
    app.state.accounts_code = {module.id: module for module in discover(settings.modules_path)}['L01.accounts'].load
    app.state.test_owner_url, app.state.test_owner_answers = database_owner_url, ownership
    async with app.router.lifespan_context(app):
        # Its first sweep takes its start number too; taking it here first keeps the order fixed.
        await start_number(app)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://localhost:3000', headers=ORIGIN) as client:
            yield app, client


@asynccontextmanager
async def replica(database_url, keys):
    """Another Identity process on the same database, started now: it takes its start number, as
    its first sweep would, but it has no lifespan, so its sweep never runs."""
    settings = Settings(database_url=database_url, service_name='identity', auth_public_key=keys[1])
    app = create_app(settings)
    app.state.accounts_code = {module.id: module for module in discover(settings.modules_path)}['L01.accounts'].load
    app.state.pool = await db.create_pool(database_url)
    await start_number(app)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://localhost:3000', headers=ORIGIN) as client:
            yield app, client
    finally:
        await app.state.pool.close()


@asynccontextmanager
async def as_owner(app):
    """A connection as the test database's owner, in the seed's own output formats, as the seed connects."""
    owner = await asyncpg.connect(app.state.test_owner_url, server_settings=getattr(demo_seed, 'FORMATS', None))
    try:
        yield owner
    finally:
        await owner.close()


async def seeded(app, sample, role, *, sample_set='demo', listed=True, created=True, recorded=True):
    """A sample account as the deploy seed makes it: at the seed's pinned id and address, entered in
    the seed's ownership record unless recorded is False, and on the list when listed."""
    account_id, email = session_slots.seed_account(sample_set, role)
    account = session_slots.SampleAccount(sample_set, role, email, account_id)
    if created:
        hash_password = app.state.accounts_code('security.py:hash_password')
        # The owner writes, as the seed does: the runtime role may only read the ownership record.
        async with as_owner(app) as owner, owner.transaction():
            await owner.execute('INSERT INTO identity_accounts(id,email,display_name,password_hash) VALUES($1,$2,$3,$4)',
                                account_id, email, 'DEMO ' + role, hash_password(secrets.token_urlsafe(24)))
            if recorded and OWNER_CHECK is not None:
                await demo_seed.record(owner, demo_seed.account(sample_set, role).key, 'identity_accounts', {'id': account_id})
        if recorded and OWNER_CHECK is None:
            app.state.test_owner_answers[sample_set, role] = 'owned'
    if listed:
        sample[sample_set, role] = account
    return account


def switch_on(monkeypatch, *, key=None, until=None):
    key = key or secrets.token_urlsafe(32)
    until = until or datetime.now(timezone.utc) + timedelta(hours=2)
    monkeypatch.setenv('BT_DEMO_ENTRY_UNTIL', until.isoformat())
    monkeypatch.setenv('BT_DEMO_ENTRY_KEY_SHA256', hashlib.sha256(key.encode()).hexdigest())
    return key, until


def switch_off(monkeypatch):
    monkeypatch.delenv('BT_DEMO_ENTRY_UNTIL', raising=False)
    monkeypatch.delenv('BT_DEMO_ENTRY_KEY_SHA256', raising=False)


async def start_number(app):
    """The process's place in the order of process starts, which the database issues."""
    return await app.state.accounts_code('demo_entry.py:start_number')(app)


async def restart(app):
    """What a new process does at start: take a new start number from the database, then put its values on record."""
    app.state.demo_start = None
    await app.state.accounts_code('demo_entry.py:register_settings')(app)


def serving(monkeypatch, values):
    """The switch values are process-wide here, so each step first sets its process's own:
    None for the switch off, or (key, end time, Operator setting)."""
    if values is None:
        switch_off(monkeypatch)
    else:
        switch_on(monkeypatch, key=values[0], until=values[1])
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, values[2])


def new_slot():
    return secrets.token_urlsafe(16)


def slotted(slot, cookie=None):
    headers = {'X-BT-Session-Slot': slot}
    if cookie:
        headers['Cookie'] = 'bt_refresh_s_' + slot + '=' + cookie
    return headers


def issued(response):
    """The one Set-Cookie header as (name, value, attributes)."""
    [header] = response.headers.get_list('set-cookie')
    pair, *rest = [part.strip() for part in header.split(';')]
    name, value = pair.split('=', 1)
    attributes = {}
    for part in rest:
        label, _, setting = part.partition('=')
        attributes[label.lower()] = setting or True
    return name, value.strip('"'), attributes


def auth(session):
    return {'Authorization': 'Bearer ' + session['access_token']}


def session_id(response):
    return UUID(response.json()['principal']['actor']['session_id'])


async def enter(client, role, key, slot=None, sample_set='demo'):
    response = await client.post('/v1/demo-entry/sessions', headers=slotted(slot or new_slot()), json={'set': sample_set, 'role': role, 'key': key})
    client.cookies.clear()
    return response


async def register(client, email):
    response = await client.post('/v1/accounts/register', headers={'Idempotency-Key': 'register-' + secrets.token_hex(8)},
        json={'email': email, 'password': PASSWORD, 'display_name': 'Sample'})
    assert response.status_code == 201, response.text
    client.cookies.clear()
    return response.json()


async def slot_login(client, email, slot):
    response = await client.post('/v1/accounts/login', headers=slotted(slot), json={'email': email, 'password': PASSWORD})
    client.cookies.clear()
    return response


async def ordinary_login(client, email):
    response = await client.post('/v1/accounts/login', json={'email': email, 'password': PASSWORD})
    client.cookies.clear()
    return response


async def outsider(client):
    """An ordinary registered account, signed in in an ordinary tab; seed accounts have no usable password."""
    await register(client, OUTSIDER)
    signed_in = await ordinary_login(client, OUTSIDER)
    assert signed_in.status_code == 200, signed_in.text
    return signed_in


async def counts(app):
    async with app.state.pool.acquire() as tx:
        return {table: await tx.fetchval(f'SELECT count(*) FROM {table}') for table in TABLES}


async def revoked(app, session):
    async with app.state.pool.acquire() as tx:
        return await tx.fetchval('SELECT revoked_at IS NOT NULL FROM identity_sessions WHERE id=$1', session)


async def principal(client, session):
    return (await client.get('/internal/v1/principal', headers=auth(session.json()))).status_code


async def refresh(client, slot, session):
    response = await client.post('/v1/accounts/refresh', headers=slotted(slot, issued(session)[1]))
    client.cookies.clear()
    return response


async def standin_operator(app, client, monkeypatch, email=STANDIN):
    """The demo operator's stand-in: registered, made the first platform operator, then named by the setting."""
    registered = await register(client, email)
    await bootstrap_operator.bootstrap(app.state.pool, email, STANDIN_REASON)
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, email)
    return UUID(registered['account']['id'])


async def second_operator(app, client):
    """A second stand-in operator. First-operator bootstrap runs once per database, so it gets a copy of the first stand-in's grant."""
    subject = UUID((await register(client, SECOND_STANDIN))['account']['id'])
    async with app.state.pool.acquire() as tx:
        await tx.execute('''INSERT INTO identity_access_grants(id,subject_id,role,permissions)
            SELECT $1,$2,g.role,g.permissions FROM identity_access_grants g JOIN identity_accounts a ON a.id=g.subject_id
            WHERE a.email=$3 AND g.organization_id IS NULL AND g.role='operator' AND g.revoked_at IS NULL''', uuid4(), subject, STANDIN)
    return subject


async def held(app, subject):
    """Everything the Operator link must never change about an account: its row (password and
    address included), grants, memberships, contacts, second factors, and its ordinary sessions
    with their refresh handles."""
    rows = {}
    async with app.state.pool.acquire() as tx:
        for table, match in (('identity_accounts', 'id=$1'), ('identity_access_grants', 'subject_id=$1'),
                             ('l02_memberships', 'subject_id=$1'), ('l02_contacts', 'subject_id=$1'),
                             ('identity_l19_factors', 'subject_id=$1::uuid::text')):
            if await tx.fetchval('SELECT to_regclass($1) IS NOT NULL', table):
                rows[table] = sorted(map(dict, await tx.fetch(f'SELECT * FROM {table} WHERE {match}', subject)), key=repr)
        rows['ordinary sessions'] = sorted(map(dict, await tx.fetch('''SELECT s.*, t.hash, t.consumed_at FROM identity_sessions s
            LEFT JOIN identity_refresh_tokens t ON t.session_id=s.id WHERE s.subject_id=$1
            AND NOT EXISTS(SELECT 1 FROM identity_demo_sessions d WHERE d.session_id=s.id)''', subject)), key=repr)
    assert rows['identity_accounts'], 'the account must exist'
    return rows


def power(body):
    """A principal's power, without the session it belongs to."""
    found = dict(body['principal'])
    found['actor'] = {key: value for key, value in found['actor'].items() if key != 'session_id'}
    return found


@pytest.mark.asyncio
@pytest.mark.parametrize('setting', ['unset', 'until-only', 'key-only', 'past', 'beyond-a-day', 'no-zone', 'bad-digest'])
async def test_switch_off_answers_404_and_creates_nothing(environment, sample, monkeypatch, setting):
    app, client = environment
    await seeded(app, sample, 'buyer')
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, STANDIN)
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(hours=1)).isoformat()
    digest = hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()
    values = {
        'unset': {}, 'until-only': {'BT_DEMO_ENTRY_UNTIL': soon}, 'key-only': {'BT_DEMO_ENTRY_KEY_SHA256': digest},
        'past': {'BT_DEMO_ENTRY_UNTIL': (now - timedelta(minutes=1)).isoformat(), 'BT_DEMO_ENTRY_KEY_SHA256': digest},
        'beyond-a-day': {'BT_DEMO_ENTRY_UNTIL': (now + timedelta(hours=25)).isoformat(), 'BT_DEMO_ENTRY_KEY_SHA256': digest},
        'no-zone': {'BT_DEMO_ENTRY_UNTIL': (now + timedelta(hours=1)).replace(tzinfo=None).isoformat(), 'BT_DEMO_ENTRY_KEY_SHA256': digest},
        'bad-digest': {'BT_DEMO_ENTRY_UNTIL': soon, 'BT_DEMO_ENTRY_KEY_SHA256': 'not-a-digest'},
    }[setting]
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    responses = [await client.post('/v1/demo-entry/sessions', headers=slotted(new_slot()), json={'set': 'demo', 'role': role, 'key': 'x' * 40})
                 for role in ('buyer', 'operator')]
    malformed = await client.post('/v1/demo-entry/sessions', content=b'not json')
    assert [response.status_code for response in responses] == [404, 404] and malformed.status_code == 404
    assert not any('set-cookie' in response.headers for response in responses)
    assert await counts(app) == dict.fromkeys(TABLES, 0)


@pytest.mark.asyncio
async def test_entry_signs_one_slot_in_as_the_seed_account_with_session_cookie_cap_and_audit(environment, sample, monkeypatch):
    app, client = environment
    account = await seeded(app, sample, 'buyer')
    key, until = switch_on(monkeypatch)
    slot = new_slot()
    entered = await enter(client, 'buyer', key, slot)
    assert entered.status_code == 200, entered.text
    assert entered.json()['account']['id'] == str(account.account_id) and entered.json()['principal']['roles'] == ['buyer']
    name, value, attributes = issued(entered)
    assert name == 'bt_refresh_s_' + slot and 32 <= len(value) <= 200
    assert attributes.get('httponly') is True and attributes.get('path') == '/' and str(attributes.get('samesite')).lower() == 'strict'
    assert not {'max-age', 'expires', 'domain'} & set(attributes)
    session = session_id(entered)
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT expires_at FROM identity_sessions WHERE id=$1', session) <= until
        assert await tx.fetchval('SELECT role FROM identity_demo_sessions WHERE session_id=$1', session) == 'buyer'
        assert await tx.fetchval('SELECT count(*) FROM identity_demo_activations WHERE closed_at IS NULL') == 1
        audit = await tx.fetchrow("SELECT * FROM identity_security_audit WHERE action='demo-entry.session'")
        assert (audit['outcome'], audit['actor_id'], audit['resource_id']) == ('accepted', account.account_id, session)
    assert await principal(client, entered) == 200
    refreshed = await client.post('/v1/accounts/refresh', headers=slotted(slot, value))
    client.cookies.clear()
    assert refreshed.status_code == 200 and refreshed.json()['account']['id'] == str(account.account_id)
    assert issued(refreshed)[0] == 'bt_refresh_s_' + slot and 'max-age' not in issued(refreshed)[2]
    # The slot cookie means nothing to an ordinary tab, nor to another slot.
    assert (await client.post('/v1/accounts/refresh', headers={'Cookie': 'bt_refresh_s_' + slot + '=' + issued(refreshed)[1]})).status_code == 401
    assert (await client.post('/v1/accounts/refresh', headers={'X-BT-Session-Slot': new_slot(), 'Cookie': 'bt_refresh_s_' + slot + '=' + issued(refreshed)[1]})).status_code == 401


@pytest.mark.asyncio
async def test_a_link_access_token_never_outlives_the_demo_end_time(environment, sample, monkeypatch):
    app, client = environment
    await seeded(app, sample, 'buyer')
    key, until = switch_on(monkeypatch, until=datetime.now(timezone.utc) + timedelta(seconds=90))
    slot = new_slot()
    entered = await enter(client, 'buyer', key, slot)
    assert entered.status_code == 200, entered.text
    claims = jwt.decode(entered.json()['access_token'], options={'verify_signature': False})
    assert claims['exp'] <= until.timestamp() and entered.json()['expires_in'] <= 90
    refreshed = await refresh(client, slot, entered)
    assert refreshed.status_code == 200
    assert jwt.decode(refreshed.json()['access_token'], options={'verify_signature': False})['exp'] <= until.timestamp()
    # An ordinary sign-in keeps its usual five minutes.
    ordinary = await outsider(client)
    assert ordinary.json()['expires_in'] > 290


@pytest.mark.asyncio
async def test_slot_cookie_is_secure_outside_local_http(environment, sample, monkeypatch):
    app, client = environment
    await seeded(app, sample, 'buyer')
    key, _ = switch_on(monkeypatch)
    monkeypatch.delenv('BT_LOCAL_HTTP')
    entered = await enter(client, 'buyer', key)
    assert entered.status_code == 200
    attributes = issued(entered)[2]
    assert attributes.get('secure') is True and attributes.get('httponly') is True and 'max-age' not in attributes


@pytest.mark.asyncio
@pytest.mark.parametrize('wrong', ['wrong-length', 'short', 'empty-slot'])
async def test_wrong_key_or_missing_slot_is_refused(environment, sample, monkeypatch, wrong):
    app, client = environment
    await seeded(app, sample, 'buyer')
    key, _ = switch_on(monkeypatch)
    before = await counts(app)
    body = {'set': 'demo', 'role': 'buyer', 'key': {'wrong-length': secrets.token_urlsafe(32), 'short': key[:10], 'empty-slot': key}[wrong]}
    headers = {} if wrong == 'empty-slot' else slotted(new_slot())
    response = await client.post('/v1/demo-entry/sessions', headers=headers, json=body)
    assert 'set-cookie' not in response.headers
    after = await counts(app)
    assert after['identity_sessions'] == before['identity_sessions'] and after['identity_demo_sessions'] == 0
    if wrong == 'empty-slot':
        assert response.status_code == 400 and response.json()['error']['code'] == 'invalid_session_slot'
    else:
        assert response.status_code == 401 and response.json()['error']['code'] == 'demo_entry_refused'
        async with app.state.pool.acquire() as tx:
            assert await tx.fetchval("SELECT outcome FROM identity_security_audit WHERE action='demo-entry.session'") == 'denied'


@pytest.mark.asyncio
async def test_entry_names_only_seed_sets_and_roles_and_only_accounts_the_seed_made(environment, sample, monkeypatch):
    app, client = environment
    await register(client, OUTSIDER)
    await seeded(app, sample, 'buyer')
    await seeded(app, sample, 'staff', created=False)
    key, _ = switch_on(monkeypatch)
    for body in ({'set': 'demo', 'role': 'admin', 'key': key}, {'set': 'demo', 'role': 'brand', 'key': key},
                 {'set': 'demo', 'role': 'dealer', 'key': key}, {'set': 'sunday', 'role': 'buyer', 'key': key},
                 {'role': 'buyer', 'key': key}, {'set': 'demo', 'role': 'buyer', 'key': key, 'email': OUTSIDER},
                 {'set': 'demo', 'role': 'buyer', 'key': key, 'account_id': str(UUID(int=1))}):
        response = await client.post('/v1/demo-entry/sessions', headers=slotted(new_slot()), json=body)
        assert response.status_code == 422 and 'set-cookie' not in response.headers
    # A role or set the list does not name, and a listed account the seed has not made yet: nothing is created.
    for role, sample_set in (('buyer', 'click-test'), ('staff', 'demo')):
        response = await enter(client, role, key, sample_set=sample_set)
        assert response.status_code == 409 and response.json()['error']['code'] == 'sample_account_unavailable'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM identity_demo_sessions') == 0


@pytest.mark.asyncio
async def test_each_set_link_enters_that_sets_own_account(environment, sample, monkeypatch):
    app, client = environment
    demo = await seeded(app, sample, 'buyer')
    click = await seeded(app, sample, 'buyer', sample_set='click-test')
    key, _ = switch_on(monkeypatch)
    for sample_set, account in (('demo', demo), ('click-test', click)):
        entered = await enter(client, 'buyer', key, sample_set=sample_set)
        assert entered.status_code == 200 and entered.json()['account']['id'] == str(account.account_id)
        assert await principal(client, entered) == 200


@pytest.mark.asyncio
async def test_registration_at_a_listed_address_gets_no_link_and_no_slot(environment, sample, monkeypatch):
    app, client = environment
    # The seed has not run, so the listed address is free and anyone could register it.
    await seeded(app, sample, 'buyer', created=False)
    registered = (await register(client, BUYER))['account']
    assert UUID(registered['id']).version == 4
    key, _ = switch_on(monkeypatch)
    entered = await enter(client, 'buyer', key)
    assert entered.status_code == 409 and entered.json()['error']['code'] == 'sample_account_unavailable'
    typed = await slot_login(client, BUYER, new_slot())
    assert typed.status_code == 403 and typed.json()['error']['code'] == 'slot_unavailable' and 'set-cookie' not in typed.headers
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM identity_demo_sessions') == 0
        assert await tx.fetchval('SELECT count(*) FROM identity_sessions WHERE subject_id=$1', UUID(registered['id'])) == 1
        assert await tx.fetchval("SELECT count(*) FROM identity_security_audit WHERE outcome='denied'") == 1
    # The same account still signs in, in an ordinary tab, exactly as before.
    ordinary = await ordinary_login(client, BUYER)
    assert ordinary.status_code == 200 and issued(ordinary)[0] == 'bt_refresh'


@pytest.mark.asyncio
@pytest.mark.parametrize('switch', ['off', 'on'])
async def test_a_typed_sign_in_or_registration_never_gets_a_slot(environment, sample, monkeypatch, switch):
    app, client = environment
    await seeded(app, sample, 'buyer')
    await register(client, OUTSIDER)
    if switch == 'on':
        switch_on(monkeypatch)
    before = await counts(app)
    # A slot holds only a link session: a typed password is refused there for every account,
    # the listed seed accounts included, before any account is read or any attempt counted.
    for email in (OUTSIDER, BUYER):
        refused = await slot_login(client, email, new_slot())
        assert refused.status_code == 403 and refused.json()['error']['code'] == 'slot_unavailable'
        assert 'set-cookie' not in refused.headers
    registered = await client.post('/v1/accounts/register', headers={**slotted(new_slot()), 'Idempotency-Key': 'register-in-slot'},
        json={'email': 'new@example.test', 'password': PASSWORD, 'display_name': 'Sample'})
    assert registered.status_code == 403 and registered.json()['error']['code'] == 'slot_unavailable'
    assert await counts(app) == before
    # An ordinary tab still signs an ordinary account in exactly as before.
    ordinary = await ordinary_login(client, OUTSIDER)
    name, _, attributes = issued(ordinary)
    assert ordinary.status_code == 200 and name == 'bt_refresh' and attributes.get('max-age') == str(7 * 24 * 3600)
    # An ordinary session never works from a slot.
    moved = await client.post('/v1/accounts/refresh', headers=slotted(new_slot(), issued(ordinary)[1]))
    assert moved.status_code == 401


@pytest.mark.asyncio
async def test_slot_sessions_end_when_the_account_leaves_the_list(environment, sample, monkeypatch):
    app, client = environment
    await seeded(app, sample, 'buyer')
    await seeded(app, sample, 'staff')
    key, _ = switch_on(monkeypatch)
    buyer_slot, staff_slot = new_slot(), new_slot()
    buyer, staff = await enter(client, 'buyer', key, buyer_slot), await enter(client, 'staff', key, staff_slot)
    assert buyer.status_code == staff.status_code == 200
    sample.clear()
    # Checked by a principal call first, or by its refresh alone.
    assert await principal(client, staff) == 401
    for slot, response in ((buyer_slot, buyer), (staff_slot, staff)):
        assert (await refresh(client, slot, response)).status_code == 401
    assert await revoked(app, session_id(buyer)) and await revoked(app, session_id(staff))


@pytest.mark.asyncio
async def test_two_slots_in_one_browser_hold_two_roles_and_sign_out_independently(environment, sample, monkeypatch):
    app, client = environment
    await seeded(app, sample, 'buyer')
    await seeded(app, sample, 'staff')
    buyer_slot, staff_slot = new_slot(), new_slot()
    key, _ = switch_on(monkeypatch)
    buyer, staff = await enter(client, 'buyer', key, buyer_slot), await enter(client, 'staff', key, staff_slot)
    assert buyer.status_code == staff.status_code == 200
    assert issued(buyer)[0] == 'bt_refresh_s_' + buyer_slot and issued(staff)[0] == 'bt_refresh_s_' + staff_slot
    both = 'bt_refresh_s_' + buyer_slot + '=' + issued(buyer)[1] + '; bt_refresh_s_' + staff_slot + '=' + issued(staff)[1]
    signed_out = await client.post('/v1/accounts/logout', headers={'X-BT-Session-Slot': staff_slot, 'Cookie': both})
    client.cookies.clear()
    assert signed_out.status_code == 200 and issued(signed_out)[0] == 'bt_refresh_s_' + staff_slot
    assert (await refresh(client, staff_slot, staff)).status_code == 401
    kept = await client.post('/v1/accounts/refresh', headers={'X-BT-Session-Slot': buyer_slot, 'Cookie': both})
    client.cookies.clear()
    assert kept.status_code == 200 and kept.json()['account']['email'] == BUYER
    assert await principal(client, buyer) == 200 and await principal(client, staff) == 401
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM identity_demo_sessions') == 2


@pytest.mark.asyncio
async def test_turning_the_switch_off_ends_link_sessions_only(environment, sample, monkeypatch):
    app, client = environment
    await standin_operator(app, client, monkeypatch)
    key, _ = switch_on(monkeypatch)
    link_slot = new_slot()
    link = await enter(client, 'operator', key, link_slot)
    # The same account's ordinary sign-in, in an ordinary tab.
    ordinary = await ordinary_login(client, STANDIN)
    assert link.status_code == ordinary.status_code == 200
    assert await principal(client, link) == 200
    switch_off(monkeypatch)
    assert await principal(client, link) == 401
    assert (await refresh(client, link_slot, link)).status_code == 401
    assert await principal(client, ordinary) == 200
    assert (await client.post('/v1/accounts/refresh', headers={'Cookie': 'bt_refresh=' + issued(ordinary)[1]})).status_code == 200
    client.cookies.clear()
    assert (await enter(client, 'operator', key)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['off-then-same-values', 'new-key-then-old-key', 'new-end-time'])
async def test_turning_entry_off_or_changing_its_values_is_final(environment, sample, monkeypatch, change):
    app, client = environment
    await seeded(app, sample, 'buyer')
    key, until = switch_on(monkeypatch)
    first_slot = new_slot()
    first = await enter(client, 'buyer', key, first_slot)
    assert first.status_code == 200 and await principal(client, first) == 200
    if change == 'off-then-same-values':
        switch_off(monkeypatch)
    elif change == 'new-key-then-old-key':
        switch_on(monkeypatch, until=until)
    else:
        switch_on(monkeypatch, key=key, until=until + timedelta(minutes=5))
    # Each deploy with changed values starts a new process.
    await restart(app)
    assert await revoked(app, session_id(first)) and await principal(client, first) == 401
    # Setting the earlier values again never brings the earlier activation back.
    switch_on(monkeypatch, key=key, until=until)
    await restart(app)
    assert await principal(client, first) == 401
    assert (await refresh(client, first_slot, first)).status_code == 401
    assert (await enter(client, 'buyer', key)).status_code == 404
    async with app.state.pool.acquire() as tx:
        # Only the values in between, which still hold the record, stay open; turning entry off closed everything.
        assert await tx.fetchval('SELECT count(*) FROM identity_demo_activations WHERE closed_at IS NULL') == (
            0 if change == 'off-then-same-values' else 1)
    # A fresh key opens a fresh activation.
    fresh, _ = switch_on(monkeypatch)
    await restart(app)
    again = await enter(client, 'buyer', fresh)
    assert again.status_code == 200 and await principal(client, again) == 200 and await principal(client, first) == 401


@pytest.mark.asyncio
async def test_a_restart_keeps_the_current_activation_open(environment, sample, monkeypatch):
    app, client = environment
    await seeded(app, sample, 'buyer')
    key, _ = switch_on(monkeypatch)
    entered = await enter(client, 'buyer', key)
    await restart(app)
    assert not await revoked(app, session_id(entered)) and await principal(client, entered) == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('earlier', ['used', 'unused', 'unseen'])
@pytest.mark.parametrize('change', ['new-key', 'operator', 'off'])
async def test_a_newer_deploy_fences_earlier_values_on_every_replica_before_any_sweep(
        environment, database_url, keys, sample, monkeypatch, change, earlier):
    """A rolling deploy: Identity processes of two configurations on one database.

    The old process runs the earlier values. A newer one, started later and never running its
    sweep, has a new key, only a new Operator setting, or the switch off. Once the newer one has
    served one ordinary principal check, no process admits anyone under the earlier values or
    keeps their link sessions: whether those values opened link sessions ('used'), were only put
    on record ('unused'), or had never reached the database before ('unseen'). A replica of the
    earlier values started after the newer one stays closed too.
    """
    old, old_client = environment
    await seeded(old, sample, 'buyer')
    await standin_operator(old, old_client, monkeypatch)
    if change == 'operator':
        await second_operator(old, old_client)
    ordinary = await outsider(old_client)
    key, until = switch_on(monkeypatch)
    earlier_values = (key, until, STANDIN)
    earlier_activation = session_slots.demo_values().activation
    later = {'new-key': (secrets.token_urlsafe(32), until, STANDIN), 'operator': (key, until, SECOND_STANDIN), 'off': None}[change]
    links = []
    if earlier != 'unseen':
        # The old process puts its values on record, as its first sweep or request does.
        await old.state.accounts_code('demo_entry.py:register_settings')(old)
    if earlier == 'used':
        for role in ('buyer', 'operator'):
            slot = new_slot()
            link = await enter(old_client, role, key, slot)
            assert link.status_code == 200 and await principal(old_client, link) == 200
            links.append((slot, link))

    async def closed_to_earlier_values(client):
        """Served with the earlier values: no earlier link session works and no one enters."""
        for slot, link in links:
            assert await principal(client, link) == 401
            assert (await refresh(client, slot, link)).status_code == 401
        for role in ('buyer', 'operator'):
            assert (await enter(client, role, key)).status_code == 404

    async with replica(database_url, keys) as (new, new_client):
        assert new.state.demo_start > await start_number(old)
        serving(monkeypatch, later)
        later_activation = later and session_slots.demo_values().activation
        # One ordinary principal check, and the newer process has put its values on record.
        assert await principal(new_client, ordinary) == 200
        for _, link in links:
            assert await principal(new_client, link) == 401
        serving(monkeypatch, earlier_values)
        await closed_to_earlier_values(old_client)
        # Ordinary sign-in on the old process is untouched.
        assert await principal(old_client, ordinary) == 200
        async with replica(database_url, keys) as (stale, stale_client):
            assert stale.state.demo_start > new.state.demo_start
            await closed_to_earlier_values(stale_client)
            assert await principal(stale_client, ordinary) == 200
        serving(monkeypatch, later)
        if later:
            for role, email in (('buyer', BUYER), ('operator', later[2])):
                fresh = await enter(new_client, role, later[0])
                assert fresh.status_code == 200, fresh.text
                assert fresh.json()['account']['email'] == email and await principal(new_client, fresh) == 200
        else:
            assert (await enter(new_client, 'buyer', key)).status_code == 404
    async with old.state.pool.acquire() as tx:
        closed = dict(await tx.fetch('SELECT activation, closed_at IS NOT NULL FROM identity_demo_activations'))
    # The earlier values are recorded closed for good, and only the newer values are open.
    assert closed[earlier_activation] is True
    assert [activation for activation, ended in closed.items() if not ended] == ([later_activation] if later else [])


@pytest.mark.asyncio
@pytest.mark.parametrize('newer', ['new-key', 'off'])
async def test_the_database_orders_process_starts_and_turning_entry_off_is_final(
        environment, database_url, keys, sample, monkeypatch, newer):
    """Review round 4, finding 3: processes are ordered by when they started, as the database
    numbers them, never by a process clock.

    The old process puts its values on record. A process of a newer deploy starts but has not
    reached the record yet when a replacement process of the old values starts after it and puts
    them on record. Then the newer deploy's process reaches the record. With a new key, its values
    come from a process started before the replacement, so they are recorded closed and the old
    values stay in use. With the switch off, entry ends anyway: turning entry off is final
    whatever the order, so an off process numbered lower than the record still closes it.
    """
    old, old_client = environment
    await seeded(old, sample, 'buyer')
    await standin_operator(old, old_client, monkeypatch)
    ordinary = await outsider(old_client)
    key, until = switch_on(monkeypatch)
    current = (key, until, STANDIN)
    current_activation = session_slots.demo_values().activation
    later = (secrets.token_urlsafe(32), until, STANDIN) if newer == 'new-key' else None
    await old.state.accounts_code('demo_entry.py:register_settings')(old)
    slot = new_slot()
    link = await enter(old_client, 'buyer', key, slot)
    assert link.status_code == 200 and await principal(old_client, link) == 200
    async with replica(database_url, keys) as (newer_process, newer_client):
        async with replica(database_url, keys) as (again, again_client):
            assert await start_number(old) < newer_process.state.demo_start < again.state.demo_start
            # The replacement of the old process reaches the record first.
            serving(monkeypatch, current)
            assert await principal(again_client, ordinary) == 200
            # Then the newer deploy's process, which started before the replacement.
            serving(monkeypatch, later)
            later_activation = later and session_slots.demo_values().activation
            assert await principal(newer_client, ordinary) == 200
            if later:
                assert (await enter(newer_client, 'buyer', later[0])).status_code == 404
            serving(monkeypatch, current)
            if later:
                assert await principal(again_client, link) == 200 and await principal(old_client, link) == 200
                assert (await enter(again_client, 'buyer', key)).status_code == 200
            else:
                assert await principal(again_client, link) == 401 and await principal(old_client, link) == 401
                assert (await refresh(again_client, slot, link)).status_code == 401
                for client in (again_client, old_client):
                    assert (await enter(client, 'buyer', key)).status_code == 404
            assert await principal(again_client, ordinary) == 200 and await principal(old_client, ordinary) == 200
    async with old.state.pool.acquire() as tx:
        fence = await tx.fetchrow('SELECT activation, start_number FROM identity_demo_fence')
        closed = dict(await tx.fetch('SELECT activation, closed_at IS NOT NULL FROM identity_demo_activations'))
    # The record keeps the replacement's number either way.
    assert fence['start_number'] == again.state.demo_start
    if later:
        assert fence['activation'] == current_activation
        assert closed == {current_activation: False, later_activation: True}
    else:
        assert fence['activation'] is None and closed == {current_activation: True}


@pytest.mark.asyncio
async def test_the_sweep_ends_link_sessions_once_their_end_time_passes(environment, sample, monkeypatch):
    app, client = environment
    await seeded(app, sample, 'buyer')
    key, _ = switch_on(monkeypatch)
    entered = await enter(client, 'buyer', key)
    ordinary = await outsider(client)
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE identity_demo_activations SET until_at=now()-interval '1 second'")
    await app.state.accounts_code('demo_entry.py:close_expired')(app.state.pool)
    assert await revoked(app, session_id(entered)) and not await revoked(app, session_id(ordinary))
    assert await principal(client, entered) == 401 and await principal(client, ordinary) == 200


@pytest.mark.asyncio
async def test_a_sixth_link_tab_displaces_only_link_sessions(environment, sample, monkeypatch):
    app, client = environment
    await standin_operator(app, client, monkeypatch)
    key, _ = switch_on(monkeypatch)
    ordinary = await ordinary_login(client, STANDIN)
    links = [await enter(client, 'operator', key) for _ in range(6)]
    assert all(link.status_code == 200 for link in links)
    assert await revoked(app, session_id(links[0]))
    assert not any([await revoked(app, session_id(link)) for link in links[1:]])
    assert not await revoked(app, session_id(ordinary)) and await principal(client, ordinary) == 200
    # Six more ordinary sign-ins displace the oldest ordinary one, never a link session.
    for _ in range(6):
        assert (await ordinary_login(client, STANDIN)).status_code == 200
    assert await revoked(app, session_id(ordinary))
    assert not any([await revoked(app, session_id(link)) for link in links[1:]])


@pytest.mark.asyncio
async def test_an_exhausted_demo_budget_leaves_ordinary_sign_in_and_principal_available(environment, sample, monkeypatch):
    app, client = environment
    module = app.state.accounts_code
    await seeded(app, sample, 'buyer')
    key, _ = switch_on(monkeypatch)
    before = await outsider(client)
    for _ in range(module('demo_entry.py:REFUSED_BUDGET')):
        assert (await enter(client, 'buyer', secrets.token_urlsafe(32))).status_code == 401
    guessed = await enter(client, 'buyer', secrets.token_urlsafe(32))
    assert guessed.status_code == 429 and guessed.json()['error']['code'] == 'try_later'
    # Guessing never uses up the demo's own entry, which counts per role.
    entries = [await enter(client, 'buyer', key) for _ in range(module('demo_entry.py:ROLE_BUDGET'))]
    assert all(entry.status_code == 200 for entry in entries)
    assert (await enter(client, 'buyer', key)).status_code == 429
    assert (await ordinary_login(client, OUTSIDER)).status_code == 200
    assert await principal(client, before) == 200
    refreshed = await client.post('/v1/accounts/refresh', headers={'Cookie': 'bt_refresh=' + issued(before)[1]})
    assert refreshed.status_code == 200


@pytest.mark.asyncio
async def test_tries_from_one_tab_spend_the_role_budget_once(environment, sample, monkeypatch):
    """The browser gives up on an entry after 4 s and asks again from the same tab, at most 8 times,
    so an answer that arrives too late may already have opened a session. A tab's tries for one
    set and role spend that role's budget once per window; a ninth try, or another tab, spends again."""
    app, client = environment
    module = app.state.accounts_code
    await seeded(app, sample, 'buyer')
    key, _ = switch_on(monkeypatch)
    scope = module('security.py:digest')('demo-entry-role:demo:buyer')

    async def spent():
        async with app.state.pool.acquire() as tx:
            return await tx.fetchval('SELECT attempts FROM identity_auth_limits WHERE scope=$1', scope)

    slot = new_slot()
    for _ in range(module('demo_entry.py:SLOT_TRIES')):
        assert (await enter(client, 'buyer', key, slot)).status_code == 200
    assert await spent() == 1
    assert (await enter(client, 'buyer', key, slot)).status_code == 200
    assert await spent() == 2
    assert (await enter(client, 'buyer', key)).status_code == 200
    assert await spent() == 3


@pytest.mark.asyncio
async def test_a_refused_try_gives_its_tab_no_free_tries(environment, sample, monkeypatch):
    """Review round 4, finding 2: only a try that is admitted gives its tab tries that spend
    nothing. A tab whose first try finds the role's budget spent is refused, and so is its next
    try, which spends the budget again instead of finding a retry allowance."""
    app, client = environment
    module = app.state.accounts_code
    await seeded(app, sample, 'buyer')
    key, _ = switch_on(monkeypatch)
    budget = module('demo_entry.py:ROLE_BUDGET')
    digest = module('security.py:digest')

    async def counted(scope):
        async with app.state.pool.acquire() as tx:
            return await tx.fetchval('SELECT coalesce(sum(attempts), 0) FROM identity_auth_limits WHERE scope=$1', digest(scope))

    for _ in range(budget):
        assert (await enter(client, 'buyer', key)).status_code == 200
    slot = new_slot()
    for _ in range(2):
        refused = await enter(client, 'buyer', key, slot)
        assert refused.status_code == 429 and refused.json()['error']['code'] == 'try_later'
    assert await counted('demo-entry-role:demo:buyer') == budget + 2
    assert await counted('demo-entry-slot:' + slot + ':demo:buyer') == 0


@pytest.mark.asyncio
async def test_ordinary_tab_and_malformed_slot(environment):
    app, client = environment
    await register(client, OUTSIDER)
    ordinary = await client.post('/v1/accounts/login', json={'email': OUTSIDER, 'password': PASSWORD})
    name, value, attributes = issued(ordinary)
    assert name == 'bt_refresh' and attributes.get('max-age') == str(7 * 24 * 3600) and attributes.get('httponly') is True
    client.cookies.clear()
    assert (await client.post('/v1/accounts/refresh', headers={'Cookie': 'bt_refresh=' + value})).status_code == 200
    for slot in ('short', 'x' * 23, 'has space in it here!!', '../../../../../../../..'):
        response = await client.post('/v1/accounts/login', headers={'X-BT-Session-Slot': slot}, json={'email': OUTSIDER, 'password': PASSWORD})
        assert response.status_code == 400 and response.json()['error']['code'] == 'invalid_session_slot'


# The seed's ownership of the sample accounts (captain's ruling 261).


@needs_seed
@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['unrecorded', 'registered-at-the-address', 'made-again'])
async def test_a_sample_link_enters_only_the_row_the_seed_itself_inserted_and_recorded(environment, sample, monkeypatch, case):
    """An active row that merely matches the seed's pinned id and address is not enough."""
    app, client = environment
    if case == 'unrecorded':
        await seeded(app, sample, 'buyer', recorded=False)
        expected = 'foreign'
    elif case == 'registered-at-the-address':
        await seeded(app, sample, 'buyer', created=False)
        await register(client, BUYER)
        expected = 'foreign'
    else:
        # Deleted and made again at the same id and address, as anyone with database access could.
        account = await seeded(app, sample, 'buyer')
        async with as_owner(app) as tx:
            row = await tx.fetchrow('DELETE FROM identity_accounts WHERE id=$1 RETURNING *', account.account_id)
            await tx.execute('INSERT INTO identity_accounts(id,email,display_name,password_hash) VALUES($1,$2,$3,$4)',
                             row['id'], row['email'], row['display_name'], row['password_hash'])
        expected = 'stale'
    async with app.state.pool.acquire() as tx:
        async with tx.transaction():
            assert await OWNER_CHECK(tx, 'demo', 'buyer') == expected
    key, _ = switch_on(monkeypatch)
    refused = await enter(client, 'buyer', key)
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'sample_account_unavailable'
    assert 'set-cookie' not in refused.headers
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM identity_demo_sessions') == 0
        assert await tx.fetchval("SELECT outcome FROM identity_security_audit WHERE action='demo-entry.session'") == 'denied'


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', ['foreign', 'stale', 'missing', 'unexpected', 'no-seed-check'])
async def test_a_sample_link_refuses_every_ownership_answer_but_owned(environment, sample, monkeypatch, answer):
    """Whatever the seed's check answers other than 'owned', and in a build without that check,
    no sample role enters; the Operator link never asks it and still opens."""
    app, client = environment
    await seeded(app, sample, 'buyer')
    await standin_operator(app, client, monkeypatch)
    key, _ = switch_on(monkeypatch)
    asked = []

    async def check(tx, sample_set, role):
        asked.append((sample_set, role))
        return 'Owned' if answer == 'unexpected' else answer
    monkeypatch.setattr(session_slots, 'demo_seed', None if answer == 'no-seed-check' else SimpleNamespace(account_owner=check))
    before = await counts(app)
    refused = await enter(client, 'buyer', key)
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'sample_account_unavailable'
    assert 'set-cookie' not in refused.headers
    after = await counts(app)
    assert after['identity_sessions'] == before['identity_sessions'] and after['identity_demo_sessions'] == 0
    assert asked == ([] if answer == 'no-seed-check' else [('demo', 'buyer')])
    operator = await enter(client, 'operator', key)
    assert operator.status_code == 200 and operator.json()['account']['email'] == STANDIN
    assert asked == ([] if answer == 'no-seed-check' else [('demo', 'buyer')])


# The Operator link (captain's decision 252): the one existing account the setting names, as itself.


@pytest.mark.asyncio
async def test_the_operator_link_opens_only_the_configured_operator_with_exactly_its_own_grants(environment, sample, monkeypatch):
    app, client = environment
    await seeded(app, sample, 'buyer')
    # The seed's own operator account exists too, plain and unlisted; the link never opens it.
    await seeded(app, sample, 'operator', listed=False)
    subject = await standin_operator(app, client, monkeypatch)
    key, until = switch_on(monkeypatch)
    ordinary = await ordinary_login(client, STANDIN)
    assert ordinary.status_code == 200 and 'operator' in ordinary.json()['principal']['roles']
    for sample_set in session_slots.SETS:
        slot = new_slot()
        link = await enter(client, 'operator', key, slot, sample_set=sample_set)
        assert link.status_code == 200, link.text
        assert link.json()['account']['id'] == str(subject) and link.json()['account']['email'] == STANDIN
        # Exactly the account's own grants, as its ordinary sign-in holds them: no more, no less.
        assert power(link.json()) == power(ordinary.json())
        assert issued(link)[0] == 'bt_refresh_s_' + slot
        assert jwt.decode(link.json()['access_token'], options={'verify_signature': False})['exp'] <= until.timestamp()
        async with app.state.pool.acquire() as tx:
            assert await tx.fetchval('SELECT role FROM identity_demo_sessions WHERE session_id=$1', session_id(link)) == 'operator'
        checked = await client.get('/internal/v1/principal', headers=auth(link.json()))
        assert checked.status_code == 200
        refreshed = await refresh(client, slot, link)
        assert refreshed.status_code == 200 and refreshed.json()['account']['id'] == str(subject)
        assert power(refreshed.json()) == power(ordinary.json())
    # Typed sign-in in a slot stays refused, the operator's address included.
    typed = await slot_login(client, STANDIN, new_slot())
    assert typed.status_code == 403 and typed.json()['error']['code'] == 'slot_unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['unset', 'empty', 'blank', 'not-an-address', 'no-account', 'not-an-operator', 'sample-operator',
                                  'seed-operator-with-grant', 'click-test-seed-operator-with-grant', 'listed-sample-with-grant',
                                  'non-seed-row-at-seed-address', 'seed-id-elsewhere', 'suspended', 'revoked-grant', 'ended',
                                  'switch-off', 'past-until', 'wrong-key'])
async def test_the_operator_link_refuses_plainly_and_changes_nothing(environment, sample, monkeypatch, case):
    app, client = environment
    await seeded(app, sample, 'buyer')
    key, _ = switch_on(monkeypatch)
    named = None
    if case in ('suspended', 'revoked-grant', 'ended', 'switch-off', 'past-until', 'wrong-key'):
        named = await standin_operator(app, client, monkeypatch)
    elif case == 'not-an-operator':
        # An ordinary registered buyer: no fallback ever reaches any other account.
        named = UUID((await register(client, OUTSIDER))['account']['id'])
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, OUTSIDER)
    elif case in ('sample-operator', 'seed-operator-with-grant', 'click-test-seed-operator-with-grant'):
        # The seed's own Operator accounts (ruling 261): never the demo Operator link's account,
        # even holding operator power.
        account = await seeded(app, sample, 'operator', listed=False,
                               sample_set='click-test' if case.startswith('click-test') else 'demo')
        named = account.account_id
        if case != 'sample-operator':
            await bootstrap_operator.bootstrap(app.state.pool, account.email, STANDIN_REASON)
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, account.email)
    elif case == 'listed-sample-with-grant':
        # A listed sample account is never the Operator link's account, even holding operator power.
        named = sample['demo', 'buyer'].account_id
        await bootstrap_operator.bootstrap(app.state.pool, BUYER, STANDIN_REASON)
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, BUYER)
    elif case == 'non-seed-row-at-seed-address':
        # Registered by someone at the seed Operator's pinned address before the seed ran.
        named = UUID((await register(client, OPERATOR))['account']['id'])
        await bootstrap_operator.bootstrap(app.state.pool, OPERATOR, STANDIN_REASON)
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, OPERATOR)
    elif case == 'seed-id-elsewhere':
        # A row at the seed Operator's pinned id under another made-up address.
        moved = 'moved-standin@example.test'
        named = session_slots.seed_account('demo', 'operator')[0]
        hash_password = app.state.accounts_code('security.py:hash_password')
        async with app.state.pool.acquire() as tx:
            await tx.execute('INSERT INTO identity_accounts(id,email,display_name,password_hash) VALUES($1,$2,$3,$4)',
                             named, moved, 'Moved', hash_password(PASSWORD))
        await bootstrap_operator.bootstrap(app.state.pool, moved, STANDIN_REASON)
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, moved)
    elif case != 'unset':
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, {'empty': '', 'blank': '   ', 'not-an-address': 'operator',
                                                            'no-account': 'nobody-here@example.test'}[case])
    async with app.state.pool.acquire() as tx:
        if case == 'suspended':
            await tx.execute("UPDATE identity_accounts SET status='suspended' WHERE id=$1", named)
        elif case == 'revoked-grant':
            await tx.execute('UPDATE identity_access_grants SET revoked_at=now() WHERE subject_id=$1', named)
    if case == 'ended':
        # Past the Operator link's fixed cutoff, whatever the switch's own end time.
        monkeypatch.setattr(session_slots, 'OPERATOR_LINK_CUTOFF', datetime.now(timezone.utc) - timedelta(minutes=1))
    elif case == 'switch-off':
        switch_off(monkeypatch)
    elif case == 'past-until':
        switch_on(monkeypatch, key=key, until=datetime.now(timezone.utc) - timedelta(minutes=1))
    elif case == 'wrong-key':
        key = secrets.token_urlsafe(32)
    before = await counts(app)
    kept = named and await held(app, named)
    for sample_set in session_slots.SETS:
        refused = await enter(client, 'operator', key, sample_set=sample_set)
        assert 'set-cookie' not in refused.headers
        if case in ('switch-off', 'past-until'):
            assert refused.status_code == 404
        elif case == 'wrong-key':
            assert refused.status_code == 401 and refused.json()['error']['code'] == 'demo_entry_refused'
        else:
            assert refused.status_code == 409, refused.text
            assert refused.json()['error'] == {**refused.json()['error'], 'code': 'operator_link_unavailable',
                                               'message': 'The operator link is not set up on this site.'}
    after = await counts(app)
    assert after['identity_sessions'] == before['identity_sessions'] and after['identity_demo_sessions'] == 0
    if named:
        assert await held(app, named) == kept
    if case not in ('switch-off', 'past-until', 'wrong-key'):
        # Nothing else changes: the sample links still enter their own accounts.
        assert (await enter(client, 'buyer', key)).status_code == 200


@pytest.mark.asyncio
async def test_the_operator_link_ends_at_its_fixed_cutoff_whatever_the_end_time(environment, sample, monkeypatch):
    """The demo Operator link is for Tuesday 1 December only (ruling 252): no end time carries an
    Operator link session past the cutoff, and after it no Operator link opens or keeps working.
    The sample links keep the switch's own end time."""
    app, client = environment
    await seeded(app, sample, 'buyer')
    await standin_operator(app, client, monkeypatch)
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=90)
    monkeypatch.setattr(session_slots, 'OPERATOR_LINK_CUTOFF', cutoff)
    key, until = switch_on(monkeypatch)  # two hours ahead, well past the cutoff
    operator_slot, buyer_slot = new_slot(), new_slot()
    operator, buyer = await enter(client, 'operator', key, operator_slot), await enter(client, 'buyer', key, buyer_slot)
    assert operator.status_code == buyer.status_code == 200, (operator.text, buyer.text)
    async with app.state.pool.acquire() as tx:
        ends = {name: await tx.fetchval('SELECT expires_at FROM identity_sessions WHERE id=$1', session_id(response))
                for name, response in (('operator', operator), ('buyer', buyer))}
    assert ends['operator'] <= cutoff < ends['buyer'] <= until
    claims = jwt.decode(operator.json()['access_token'], options={'verify_signature': False})
    assert claims['exp'] <= cutoff.timestamp() and operator.json()['expires_in'] <= 90
    refreshed = await refresh(client, operator_slot, operator)
    assert refreshed.status_code == 200
    assert jwt.decode(refreshed.json()['access_token'], options={'verify_signature': False})['exp'] <= cutoff.timestamp()
    # Once the cutoff passes, the open Operator link session fails and a new one is refused.
    monkeypatch.setattr(session_slots, 'OPERATOR_LINK_CUTOFF', datetime.now(timezone.utc) - timedelta(seconds=1))
    assert await principal(client, refreshed) == 401
    assert (await refresh(client, operator_slot, refreshed)).status_code == 401
    late = await enter(client, 'operator', key)
    assert late.status_code == 409 and late.json()['error']['code'] == 'operator_link_unavailable'
    assert await principal(client, buyer) == 200
    assert (await enter(client, 'buyer', key)).status_code == 200


@pytest.mark.asyncio
async def test_the_operator_link_leaves_the_account_its_grants_and_its_other_sessions_unchanged(environment, sample, monkeypatch):
    app, client = environment
    subject = await standin_operator(app, client, monkeypatch)
    key, _ = switch_on(monkeypatch)
    ordinary = await ordinary_login(client, STANDIN)
    before = await held(app, subject)
    # Six link tabs (one more than the link-session bound), each checked and refreshed, then one signed out.
    links = []
    for _ in range(6):
        slot = new_slot()
        link = await enter(client, 'operator', key, slot)
        assert link.status_code == 200 and await principal(client, link) == 200
        refreshed = await refresh(client, slot, link)
        assert refreshed.status_code == 200
        links.append((slot, refreshed))
    slot, last = links[-1]
    signed_out = await client.post('/v1/accounts/logout', headers=slotted(slot, issued(last)[1]))
    client.cookies.clear()
    assert signed_out.status_code == 200
    # The sweep ends the rest once the end time passes.
    async with app.state.pool.acquire() as tx:
        await tx.execute("UPDATE identity_demo_activations SET until_at=now()-interval '1 second'")
    await app.state.accounts_code('demo_entry.py:close_expired')(app.state.pool)
    assert all([await revoked(app, session_id(link)) for _, link in links])
    assert await held(app, subject) == before
    # The account's own ordinary sign-in is untouched and still works.
    assert await principal(client, ordinary) == 200
    assert (await client.post('/v1/accounts/refresh', headers={'Cookie': 'bt_refresh=' + issued(ordinary)[1]})).status_code == 200
    client.cookies.clear()
    assert (await ordinary_login(client, STANDIN)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['another-account', 'removed', 'sample-account'])
async def test_changing_the_operator_setting_ends_every_link_session_of_the_old_values(environment, sample, monkeypatch, change):
    """The Operator setting is part of the activation (finding 3): changing it alone ends the old
    activation, so its Operator and sample link sessions both end; fresh links follow the new values."""
    app, client = environment
    await seeded(app, sample, 'buyer')
    await standin_operator(app, client, monkeypatch)
    key, _ = switch_on(monkeypatch)
    ordinary = await ordinary_login(client, STANDIN)
    slot, buyer_slot = new_slot(), new_slot()
    link, buyer = await enter(client, 'operator', key, slot), await enter(client, 'buyer', key, buyer_slot)
    assert link.status_code == buyer.status_code == 200
    assert await principal(client, link) == 200 and await principal(client, buyer) == 200
    if change == 'removed':
        monkeypatch.delenv(session_slots.OPERATOR_SETTING)
    else:
        if change == 'another-account':
            await register(client, OUTSIDER)
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, OUTSIDER if change == 'another-account' else BUYER)
    # Checked by a principal call, and by its refresh: neither follows the old values.
    assert await principal(client, link) == 401 and await principal(client, buyer) == 401
    assert (await refresh(client, slot, link)).status_code == 401
    assert (await refresh(client, buyer_slot, buyer)).status_code == 401
    assert await revoked(app, session_id(link)) and await revoked(app, session_id(buyer))
    # The account's ordinary sign-in is untouched, and a fresh sample link enters under the new values.
    assert await principal(client, ordinary) == 200
    assert (await enter(client, 'buyer', key)).status_code == 200
