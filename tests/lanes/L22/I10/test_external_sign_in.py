"""Synthetic contract checks; no provider round trip or runtime session proof."""
import asyncio
import importlib
import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

module = importlib.import_module('services.identity.modules.external-sign-in.service')
contract = importlib.import_module('packages.contracts-identity.external-sign-in.current')
routes = importlib.import_module('services.identity.modules.external-sign-in.routes')
Provider = importlib.import_module('services.identity.modules.external-sign-in.deterministic').DeterministicProvider
Scope, Claims, Receipt, Denied, Stale = module.Scope, module.Claims, module.Receipt, module.Denied, module.Stale


class SyntheticIdentity:
    """Contract-identical local boundary with atomic receipts, not connected proof."""
    def __init__(self, path, clock):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.clock = clock
        self.unavailable = False
        self.lose_response = False
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, recipient TEXT UNIQUE,
                revision INTEGER, active INTEGER, role TEXT DEFAULT 'buyer');
            CREATE TABLE IF NOT EXISTS links(issuer TEXT, external_subject TEXT,
                account TEXT, UNIQUE(issuer,external_subject));
            CREATE TABLE IF NOT EXISTS receipts(operation TEXT PRIMARY KEY, binding TEXT,
                subject TEXT, state TEXT, revision INTEGER, expires INTEGER, revoked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS proofs(value TEXT PRIMARY KEY, binding TEXT, expires INTEGER, used TEXT);
            CREATE TABLE IF NOT EXISTS memberships(actor TEXT, organization TEXT, active INTEGER);
        ''')

    def account(self, subject='buyer', recipient='buyer@example.test', revision=3):
        self.db.execute('INSERT INTO accounts(id,recipient,revision,active) VALUES(?,?,?,1)', (subject, recipient, revision))

    def validate(self, binding, subject):
        if self.unavailable:
            raise ConnectionError()
        account = self.db.execute('SELECT * FROM accounts WHERE id=?', (subject,)).fetchone()
        if not account or not account['active'] or account['recipient'] != binding.recipient:
            raise Denied()
        if binding.actor_id and (binding.actor_id != subject or account['revision'] != binding.expected_revision):
            raise Stale()
        if binding.organization_id and not self.db.execute(
                'SELECT 1 FROM memberships WHERE actor=? AND organization=? AND active=1',
                (subject, binding.organization_id)).fetchone():
            raise Denied()

    def proof(self, binding, value='fresh-exact-proof'):
        self.db.execute('INSERT INTO proofs VALUES(?,?,?,NULL)',
                        (value, json.dumps(asdict(binding), sort_keys=True), self.clock() + 300))
        return value

    async def complete(self, binding, proof):
        if self.unavailable:
            raise ConnectionError()
        db = self.db
        db.execute('BEGIN IMMEDIATE')
        try:
            prior = db.execute('SELECT * FROM receipts WHERE operation=?', (binding.operation_id,)).fetchone()
            encoded = json.dumps(asdict(binding), sort_keys=True)
            if prior:
                if encoded != prior['binding']:
                    raise Denied()
                self.validate(binding, prior['subject'])
                if prior['revoked'] or self.clock() >= prior['expires']:
                    raise Denied()
                receipt = Receipt(prior['subject'], prior['state'], prior['revision'])
            else:
                if self.clock() >= binding.verified_at + 600:
                    raise Denied()
                linked = db.execute('SELECT account FROM links WHERE issuer=? AND external_subject=?',
                                    (binding.issuer, binding.external_subject)).fetchone()
                owner = db.execute('SELECT id FROM accounts WHERE recipient=?', (binding.recipient,)).fetchone()
                if binding.actor_id:
                    subject = binding.actor_id
                    self.validate(binding, subject)
                    if linked and linked['account'] != subject:
                        raise Denied()
                    accepted = db.execute('''UPDATE proofs SET used=? WHERE value=? AND binding=?
                        AND expires>? AND used IS NULL''',
                        (binding.operation_id, proof, encoded, self.clock())).rowcount
                    if not accepted:
                        raise Denied()
                    state = 'linked'
                elif linked:
                    subject = linked['account']
                    self.validate(binding, subject)
                    state = 'signed_in'
                elif owner:
                    raise Denied()
                else:
                    subject, state = 'new-' + binding.operation_id, 'signed_in'
                    db.execute('INSERT INTO accounts(id,recipient,revision,active) VALUES(?,?,0,1)',
                               (subject, binding.recipient))
                db.execute('INSERT OR IGNORE INTO links VALUES(?,?,?)',
                           (binding.issuer, binding.external_subject, subject))
                revision = db.execute('SELECT revision FROM accounts WHERE id=?', (subject,)).fetchone()[0]
                receipt = Receipt(subject, state, revision)
                db.execute('INSERT INTO receipts(operation,binding,subject,state,revision,expires) VALUES(?,?,?,?,?,?)',
                           (binding.operation_id, encoded, subject, state, revision, self.clock() + 3600))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        if self.lose_response:
            self.lose_response = False
            raise ConnectionError()
        return receipt

    async def current(self, binding):
        row = self.db.execute('SELECT * FROM receipts WHERE operation=?', (binding.operation_id,)).fetchone()
        if not row:
            raise ConnectionError()
        self.validate(binding, row['subject'])
        if row['binding'] != json.dumps(asdict(binding), sort_keys=True) or row['revoked'] or self.clock() >= row['expires']:
            raise Denied()
        return Receipt(row['subject'], row['state'], row['revision'])


@pytest.fixture
def setup(tmp_path):
    now = [10000]
    def clock():
        return now[0]
    provider = Provider({})
    identity = SyntheticIdentity(str(tmp_path / 'identity.db'), clock)
    store = module.Store(str(tmp_path / 'challenges.db'))
    service = module.Service(store, provider, identity, issuer='https://identity.example.test',
                             audience='beirut-time', clock=clock, deadline=.03)
    scope = Scope('b' * 48)
    yield service, provider, identity, scope, now, tmp_path
    service.store.close()
    identity.db.close()


def start(setup, *, scope=None, operation='operation_00000001', changes=None):
    service, provider, _, default_scope, now, _ = setup
    scope = scope or default_scope
    challenge = service.begin(operation, scope)
    claims = Claims(service.issuer, service.audience, 'external-person', 'buyer@example.test',
                    True, challenge['nonce'], now[0], now[0] + 600)
    if changes:
        claims = replace(claims, **changes)
    provider.fixtures['synthetic-code'] = claims
    command = contract.Callback(operation_id=operation, expected_revision=scope.revision,
                                state=challenge['state'], code='synthetic-code')
    return command, challenge


def run(awaitable):
    return asyncio.run(awaitable)


def callback(setup, command, scope=None, proof=''):
    return run(setup[0].callback(command, scope or setup[3], proof))


def test_positive_duplicate_restart_and_current_revocation(setup):
    service, provider, identity, scope, _, path = setup
    command, _ = start(setup)
    first = callback(setup, command)
    assert first['state'] == 'signed_in'
    contract.CurrentOperation.model_validate(first)
    assert callback(setup, command) == first
    assert provider.calls == 1
    assert identity.db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 1
    assert identity.db.execute('SELECT role FROM accounts').fetchone()[0] == 'buyer'
    service.store.close()
    service.store = module.Store(str(path / 'challenges.db'))
    assert run(service.lookup(command.operation_id, scope)) == first
    identity.db.execute('UPDATE receipts SET revoked=1')
    recovered = service.begin(command.operation_id, scope)
    assert recovered['state'] == 'pending' and recovered['subject_id'] is None
    assert run(service.lookup(command.operation_id, scope))['state'] == 'denied'


@pytest.mark.parametrize('changes', [
    {'issuer': 'https://wrong.example.test'}, {'audience': 'wrong'}, {'nonce': 'wrong'},
    {'recipient_verified': False}, {'recipient_verified': 'true'}, {'recipient_verified': 1},
    {'recipient': ''}, {'recipient': 'wrong recipient@example.test'}, {'subject': ''},
    {'issued_at': 10001}, {'expires_at': 10000}, {'expires_at': 9999},
])
def test_invalid_identity_never_creates_session(setup, changes):
    command, _ = start(setup, changes=changes)
    with pytest.raises(Denied):
        callback(setup, command)
    assert setup[2].db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 0


@pytest.mark.parametrize('offset,state', [(599, 'signed_in'), (600, 'denied'), (601, 'denied')])
def test_challenge_boundary(setup, offset, state):
    command, _ = start(setup)
    setup[4][0] += offset
    assert callback(setup, command)['state'] == state


def test_invalid_signature_state_and_bounded_failures(setup):
    command, _ = start(setup)
    setup[1].fixtures['synthetic-code'] = Denied()
    with pytest.raises(Denied):
        callback(setup, command)
    bad = command.model_copy(update={'state': 'x' * 43})
    for _ in range(4):
        with pytest.raises(Denied):
            callback(setup, bad)
    assert callback(setup, command)['state'] == 'denied'
    assert setup[1].calls == 1


@pytest.mark.parametrize('scope', [Scope('c' * 48), Scope('b' * 48, 'other'), Scope('b' * 48, None, 'other')])
def test_cross_browser_actor_organization_denied(setup, scope):
    command, _ = start(setup)
    with pytest.raises(Denied):
        callback(setup, command, scope)
    with pytest.raises(Denied):
        run(setup[0].lookup(command.operation_id, scope))
    assert setup[1].calls == 0


def test_stale_command_and_scope(setup):
    command, _ = start(setup)
    assert callback(setup, command.model_copy(update={'expected_revision': 1}))['state'] == 'stale'
    with pytest.raises(Stale):
        callback(setup, command, replace(setup[3], revision=1))
    assert setup[1].calls == 0


def test_email_collision_does_not_take_over(setup):
    setup[2].account()
    command, _ = start(setup)
    assert callback(setup, command)['state'] == 'denied'
    assert setup[2].db.execute('SELECT count(*) FROM links').fetchone()[0] == 0
    assert setup[2].db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 0


def exact_proof(setup, command, scope, challenge, proof='fresh-exact-proof'):
    binding = module.Binding(command.operation_id, module.digest(scope.browser), scope.actor_id,
                             scope.organization_id, scope.revision, setup[0].issuer, 'external-person',
                             'buyer@example.test', module.digest(proof), setup[4][0])
    setup[2].proof(binding, proof)
    return proof


def test_link_requires_proof_both_sides_and_never_grants_roles(setup):
    service, _, identity, browser, _, _ = setup
    identity.account()
    scope = replace(browser, actor_id='buyer', revision=3)
    command, challenge = start(setup, scope=scope)
    proof = exact_proof(setup, command, scope, challenge)
    assert callback(setup, command, scope, proof)['state'] == 'linked'
    assert callback(setup, command, scope, proof)['state'] == 'linked'
    assert identity.db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 1
    assert identity.db.execute('SELECT role FROM accounts').fetchone()[0] == 'buyer'
    identity.db.execute('UPDATE accounts SET revision=4')
    assert run(service.lookup(command.operation_id, scope))['state'] == 'stale'


@pytest.mark.parametrize('case', ['absent', 'wrong', 'expired', 'other_external', 'used'])
def test_bad_link_proof_denies(setup, case):
    identity = setup[2]
    identity.account()
    scope = replace(setup[3], actor_id='buyer', revision=3)
    command, challenge = start(setup, scope=scope)
    proof = ''
    if case != 'absent':
        proof = exact_proof(setup, command, scope, challenge)
        if case == 'wrong':
            proof = 'other-proof'
        elif case == 'expired':
            identity.db.execute('UPDATE proofs SET expires=?', (setup[4][0],))
        elif case == 'used':
            identity.db.execute("UPDATE proofs SET used='another-operation'")
        else:
            stored = json.loads(identity.db.execute('SELECT binding FROM proofs').fetchone()[0])
            stored['external_subject'] = 'other-person'
            identity.db.execute('UPDATE proofs SET binding=?', (json.dumps(stored, sort_keys=True),))
    assert callback(setup, command, scope, proof)['state'] == 'denied'
    assert identity.db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 0


def test_business_unavailable_pending_and_membership_revocation(setup):
    identity = setup[2]
    identity.account()
    identity.db.execute("INSERT INTO memberships VALUES('buyer','business',1)")
    scope = replace(setup[3], actor_id='buyer', organization_id='business', revision=3)
    command, challenge = start(setup, scope=scope)
    proof = exact_proof(setup, command, scope, challenge)
    identity.unavailable = True
    assert callback(setup, command, scope, proof)['state'] == 'pending'
    identity.unavailable = False
    assert callback(setup, command, scope, proof)['state'] == 'linked'
    identity.db.execute('UPDATE memberships SET active=0')
    assert run(setup[0].lookup(command.operation_id, scope))['state'] == 'denied'


def test_timeout_restart_lost_response_and_changed_retry(setup):
    service, provider, identity, scope, _, path = setup
    command, _ = start(setup)
    identity.lose_response = True
    assert callback(setup, command)['state'] == 'pending'
    service.store.close()
    service.store = module.Store(str(path / 'challenges.db'))
    identity.db.close()
    identity = SyntheticIdentity(str(path / 'identity.db'), lambda: setup[4][0])
    service.identity = identity
    with pytest.raises(Denied):
        callback(setup, command.model_copy(update={'code': 'changed'}))
    assert run(service.lookup(command.operation_id, scope))['state'] == 'signed_in'
    assert identity.db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 1
    assert provider.calls == 1
    identity.db.close()


def test_actual_deadline_and_same_operation_recovery(setup):
    service, _, identity, _, _, _ = setup
    original = identity.complete
    async def slow(binding, proof):
        await asyncio.sleep(.1)
        return await original(binding, proof)
    identity.complete = slow
    command, _ = start(setup)
    assert callback(setup, command)['state'] == 'pending'
    identity.complete = original
    assert callback(setup, command)['state'] == 'signed_in'


def test_concurrent_duplicate_has_one_receipt(setup):
    command, _ = start(setup)
    async def both():
        return await asyncio.gather(setup[0].callback(command, setup[3]), setup[0].callback(command, setup[3]))
    assert all(result['state'] == 'signed_in' for result in run(both()))
    assert setup[2].db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 1


def test_creation_limits_and_replay(setup):
    service, _, _, scope, _, _ = setup
    command, _ = start(setup)
    assert service.begin(command.operation_id, scope)['state'] == command.state
    for i in range(4):
        service.begin(f'operation_extra_{i}', scope)
    with pytest.raises(Denied):
        service.begin('operation_extra_5', scope)
    assert callback(setup, command)['state'] == 'signed_in'
    another = service.begin('another_operation', Scope('z' * 48))
    replay = command.model_copy(update={'operation_id': another['operation_id'], 'state': another['state']})
    with pytest.raises(Denied):
        callback(setup, replay, Scope('z' * 48))


def test_schema_rejects_profile_grants_and_fixtures(setup):
    command, _ = start(setup)
    with pytest.raises(ValidationError):
        contract.Callback.model_validate({**command.model_dump(), 'role': 'seller'})
    with pytest.raises(ValidationError):
        contract.Callback.model_validate({**command.model_dump(), 'expected_revision': True})
    fixtures = json.loads(Path('packages/contracts-identity/external-sign-in/fixtures.json').read_text())
    assert {row['case'] for row in fixtures} == {'success', 'denied', 'stale', 'lost_response'}
    for fixture in fixtures:
        contract.CurrentOperation.model_validate(fixture['operation'])
    result = callback(setup, command)
    assert not any(value in json.dumps(result) for value in ['buyer@example.test', 'external-person', command.code, command.state])


def test_routes_scope_origin_body_privacy_and_lookup(setup):
    service = setup[0]
    command, _ = start(setup)
    async def resolve(request):
        if request.cookies.get('binding') != setup[3].browser:
            raise Denied()
        return setup[3]
    app = FastAPI()
    app.include_router(routes.router_for(service, resolve, origin='https://market.example.test'))
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://market.example.test',
                                     cookies={'binding': setup[3].browser}) as client:
            path = '/v1/external-sign-in/callback'
            assert (await client.post(path, json=command.model_dump())).status_code == 403
            client.headers['origin'] = 'https://market.example.test'
            bad = await client.post(path, content='x' * 4097)
            assert bad.status_code == 403
            response = await client.post(path, json=command.model_dump())
            assert response.status_code == 200
            assert response.json()['state'] == 'signed_in'
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['referrer-policy'] == 'no-referrer'
            del client.headers['origin']
            result = await client.get('/v1/external-sign-in/operations/' + command.operation_id)
            assert result.json() == response.json()
            client.headers['origin'] = 'https://other.example.test'
            assert (await client.get('/v1/external-sign-in/operations/' + command.operation_id)).status_code == 403
            del client.headers['origin']
            client.headers['sec-fetch-site'] = 'cross-site'
            assert (await client.get('/v1/external-sign-in/operations/' + command.operation_id)).status_code == 403
            client.headers['sec-fetch-site'] = 'same-origin'
            assert (await client.get('/v1/external-sign-in/operations/' + command.operation_id)).status_code == 200
            client.cookies.clear()
            denied = await client.get('/v1/external-sign-in/operations/' + command.operation_id)
            assert denied.status_code == 403 and 'ar' in denied.json()
    run(exercise())


def test_existing_external_identity_and_changed_recipient(setup):
    first, _ = start(setup)
    assert callback(setup, first)['state'] == 'signed_in'
    second, _ = start(setup, operation='second_operation_01')
    assert callback(setup, second)['subject_id'] == callback(setup, first)['subject_id']
    changed, _ = start(setup, operation='changed_operation01', changes={'recipient': 'other@example.test'})
    assert callback(setup, changed)['state'] == 'denied'
    assert setup[2].db.execute('SELECT count(*) FROM accounts').fetchone()[0] == 1


def test_pending_without_receipt_expires_without_session(setup):
    command, _ = start(setup)
    setup[2].unavailable = True
    assert callback(setup, command)['state'] == 'pending'
    setup[4][0] += 600
    setup[2].unavailable = False
    assert callback(setup, command)['state'] == 'denied'
    assert setup[2].db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 0


def test_unexpected_private_boundary_errors_are_sanitized(setup):
    command, _ = start(setup)
    setup[1].fixtures['synthetic-code'] = RuntimeError('private-recipient@example.test')
    assert callback(setup, command)['state'] == 'unavailable'
    assert 'private-recipient' not in json.dumps(callback(setup, command))
    setup[1].fixtures['synthetic-code'] = Claims(setup[0].issuer, setup[0].audience, 'person',
                                               'buyer@example.test', True, 'wrong-nonce', 10000, 10600)
    with pytest.raises(Denied):
        callback(setup, command)


def test_expired_ready_lookup_and_frozen_issuer_audience(setup):
    command, _ = start(setup)
    setup[0].issuer = 'https://changed.example.test'
    setup[0].audience = 'changed'
    # Original challenge configuration remains authoritative.
    assert callback(setup, command)['state'] == 'signed_in'
    command, _ = start(setup, operation='expiry_operation_01')
    setup[4][0] += 600
    assert run(setup[0].lookup(command.operation_id, setup[3]))['state'] == 'denied'


def test_challenge_response_loss_restart(setup):
    service, _, _, scope, now, path = setup
    first = service.begin('lost_challenge_01', scope)
    service.store.close()
    service.store = module.Store(str(path / 'challenges.db'))
    now[0] += 10
    assert service.begin('lost_challenge_01', scope) == first
    with pytest.raises(Denied):
        service.begin('lost_challenge_01', replace(scope, browser='x' * 48))
    assert service.store.db.execute('SELECT count(*) FROM l22_external_operations').fetchone()[0] == 1
