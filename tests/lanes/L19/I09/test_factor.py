import base64
import importlib.util
import json
import sys
from pathlib import Path
from dataclasses import replace

import pytest
from cryptography.exceptions import InvalidTag

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load('factor_contract', 'packages/contracts-identity/two-factor/current.py')
core = load('factor_core', 'services/identity/modules/two-factor/core.py')


@pytest.fixture
def setup(tmp_path):
    now = [1800000000]
    auth = [core.Authority(True, 'session-one', True, protected_producer=True)]
    key = b'k' * 32
    path = str(tmp_path / 'factor.db')
    store = core.FactorStore(path, key, lambda _: auth[0], lambda: now[0])
    yield store, now, auth, path, key
    store.close()


def command(kind, revision, **kw):
    return contract.Command(operation_id=f'operation-{kind}-{revision:04}', actor_id='person',
                            subject_id='person', expected_revision=revision, kind=kind, **kw)


def enabled(setup):
    store, now, *_ = setup
    enrollment = store.execute(command('enroll', 0))
    result = store.execute(command('confirm', 1, proof=core.totp(enrollment['secret'], now[0] // 30)))
    return enrollment, result


def scope(**kw):
    return dict(action='seller_payout', record_id='recipient', record_revision=3, **kw)


def rejects(code, fn):
    with pytest.raises(core.Rejected) as error:
        fn()
    assert error.value.code == code


def test_enrollment_confirm_and_arabic_digits(setup):
    store, now, *_ = setup
    enrollment = store.execute(command('enroll', 0))
    code = core.totp(enrollment['secret'], now[0] // 30)
    code = code.translate(str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩'))
    result = store.execute(command('confirm', 1, proof=code))
    assert result['state'] == 'enabled'
    assert len(set(result['recovery_codes'])) == 10
    rejects('invalid_proof', lambda: store.execute(command('prove', 2, proof=code, **scope())))


def test_one_use_recovery_and_bound_consumption(setup):
    store, _, *_ = setup
    _, result = enabled(setup)
    code = result['recovery_codes'][0]
    proof = store.execute(command('prove', 2, proof=code, **scope()))
    rejects('invalid_proof', lambda: store.execute(command('prove', 3, proof=code, **scope())))
    consumed = command('consume', 3, proof_id=proof['proof_id'], **scope())
    assert store.execute(consumed)['state'] == 'consumed'
    assert store.execute(consumed)['state'] == 'consumed'
    rejects('denied', lambda: store.execute(command('consume', 4, proof_id=proof['proof_id'], **scope())))


@pytest.mark.parametrize('offset,allowed', [(-1, True), (0, False), (1, False)])
def test_proof_boundary(setup, offset, allowed):
    store, now, *_ = setup
    _, result = enabled(setup)
    proof = store.execute(command('prove', 2, proof=result['recovery_codes'][0], **scope()))
    now[0] += 300 + offset
    c = command('consume', 3, proof_id=proof['proof_id'], **scope())
    if allowed:
        assert store.execute(c)['state'] == 'consumed'
    else:
        rejects('expired', lambda: store.execute(c))


@pytest.mark.parametrize('field,value', [('organization_id', 'other'), ('record_revision', 4),
                                        ('record_id', 'other'), ('action', 'privileged_review')])
def test_binding(setup, field, value):
    store, _, *_ = setup
    _, result = enabled(setup)
    proof = store.execute(command('prove', 2, proof=result['recovery_codes'][0], **scope()))
    values = scope(proof_id=proof['proof_id'])
    values[field] = value
    rejects('denied', lambda: store.execute(command('consume', 3, **values)))


def test_current_permission_and_session(setup):
    store, _, auth, *_ = setup
    _, result = enabled(setup)
    proof = store.execute(command('prove', 2, proof=result['recovery_codes'][0], **scope()))
    c = command('consume', 3, proof_id=proof['proof_id'], **scope())
    auth[0] = replace(auth[0], session_id='different')
    rejects('denied', lambda: store.execute(c))
    auth[0] = replace(auth[0], allowed=False)
    rejects('denied', lambda: store.execute(c))
    rejects('denied', lambda: store.lookup(c))


def test_restart_lost_response_and_conflict(setup):
    store, now, auth, path, key = setup
    c = command('enroll', 0)
    original = store.execute(c)
    other = core.FactorStore(path, key, lambda _: auth[0], lambda: now[0])
    try:
        assert other.execute(c) == original
        assert other.lookup(c) == original
        rejects('conflict', lambda: other.execute(c.model_copy(update={'organization_id': 'other'})))
    finally:
        other.close()


def test_stale_and_cross_account(setup):
    store, *_ = setup
    store.execute(command('enroll', 0))
    rejects('stale_revision', lambda: store.execute(command('enroll', 2)))
    rejects('denied', lambda: store.execute(command('enroll', 0).model_copy(update={'actor_id': 'other'})))


def test_private_encryption(setup):
    store, *_ = setup
    enrollment, result = enabled(setup)
    data = b''.join(row[0] for row in store.db.execute('SELECT data FROM factors'))
    data += b''.join(row[0] for row in store.db.execute('SELECT result FROM operations'))
    assert enrollment['secret'].encode() not in data
    assert result['recovery_codes'][0].encode() not in data
    sealed = store.seal('person', {'secret': 'private'})
    with pytest.raises(InvalidTag):
        store.open('other', sealed)


def test_independent_recovery_and_ack(setup):
    store, _, auth, *_ = setup
    enabled(setup)
    c = command('recover', 2, record_id='case-one')
    rejects('denied', lambda: store.execute(c))
    auth[0] = replace(auth[0], controllers=('person', 'reviewer'), recovery_case='case-one')
    rejects('denied', lambda: store.execute(c))
    auth[0] = replace(auth[0], controllers=('reviewer-one', 'reviewer-two'))
    assert store.execute(c)['state'] == 'pending'
    rejects('unavailable', lambda: store.execute(command('enroll', 3)))
    ack = command('revoke_ack', 3, proof_id=c.operation_id)
    rejects('denied', lambda: store.execute(ack))
    auth[0] = replace(auth[0], identity_producer=True)
    assert store.execute(ack)['state'] == 'sign_in_required'
    rejects('denied', lambda: store.execute(command('enroll', 4)))
    auth[0] = replace(auth[0], session_id='fresh-session')
    assert store.execute(command('enroll', 4))['state'] == 'enrolling'


def test_failed_budget_survives_restart(setup):
    store, now, auth, path, key = setup
    store.execute(command('enroll', 0))
    for _ in range(9):
        rejects('invalid_proof', lambda: store.execute(command('confirm', 1, proof='invalid')))
    store2 = core.FactorStore(path, key, lambda _: auth[0], lambda: now[0])
    try:
        rejects('try_later', lambda: store2.execute(command('confirm', 1, proof='invalid')))
    finally:
        store2.close()


@pytest.mark.parametrize('offset,allowed', [(-1, True), (0, False), (1, False)])
def test_enrollment_boundary(setup, offset, allowed):
    store, now, *_ = setup
    result = store.execute(command('enroll', 0))
    now[0] += 600 + offset
    c = command('confirm', 1, proof=core.totp(result['secret'], now[0] // 30))
    if allowed:
        assert store.execute(c)['state'] == 'enabled'
    else:
        rejects('expired', lambda: store.execute(c))


def test_provider_failure_is_unavailable(setup):
    store, *_ = setup
    def timeout(_):
        raise TimeoutError()
    store.authority = timeout
    rejects('unavailable', lambda: store.execute(command('enroll', 0)))


def test_contract_forbids_unbounded_and_extra_fields():
    with pytest.raises(ValueError):
        command('enroll', -1)
    with pytest.raises(ValueError):
        command('enroll', 0, password='private')
    fixture = json.loads((ROOT / 'packages/contracts-identity/two-factor/fixtures.json').read_text())
    assert {'confirmed', 'denied', 'stale', 'lost_response'} <= {c['name'] for c in fixture['cases']}


def test_totp_published_vector():
    secret = base64.b32encode(b'12345678901234567890').decode()
    assert core.totp(secret, 1) == '287082'


@pytest.mark.parametrize('delta', [-1, 0, 1])
def test_timestep_tolerance_and_replay(setup, delta):
    store, now, *_ = setup
    enrollment = store.execute(command('enroll', 0))
    code = core.totp(enrollment['secret'], now[0] // 30 + delta)
    store.execute(command('confirm', 1, proof=code))
    rejects('invalid_proof', lambda: store.execute(command('prove', 2, proof=code, **scope())))


def test_no_enabled_factor_replacement(setup):
    store, *_ = setup
    enabled(setup)
    rejects('denied', lambda: store.execute(command('enroll', 2)))


def test_nonproducer_cannot_consume(setup):
    store, _, auth, *_ = setup
    _, result = enabled(setup)
    proof = store.execute(command('prove', 2, proof=result['recovery_codes'][0], **scope()))
    auth[0] = replace(auth[0], protected_producer=False)
    rejects('denied', lambda: store.execute(command('consume', 3, proof_id=proof['proof_id'], **scope())))


@pytest.mark.parametrize('kind', ['enroll', 'confirm', 'prove'])
def test_private_receipts_require_issuing_session(setup, kind):
    store, _, auth, *_ = setup
    _, result = enabled(setup)
    if kind == 'enroll':
        c = command('enroll', 0)
    elif kind == 'confirm':
        c = command('confirm', 1, proof='unknown')
    else:
        c = command('prove', 2, proof=result['recovery_codes'][0], **scope())
        store.execute(c)
    auth[0] = replace(auth[0], session_id='password-only-session')
    rejects('denied', lambda: store.lookup(c))
    if kind != 'confirm':
        rejects('denied', lambda: store.execute(c))


def test_recovery_invalidates_all_old_private_receipts(setup):
    store, _, auth, *_ = setup
    enabled(setup)
    auth[0] = replace(auth[0], controllers=('reviewer-one', 'reviewer-two'), recovery_case='case-one')
    store.execute(command('recover', 2, record_id='case-one'))
    rejects('denied', lambda: store.lookup(command('enroll', 0)))
    rejects('denied', lambda: store.lookup(command('confirm', 1, proof='unknown')))


def test_expired_reenrollment_invalidates_old_secret_receipt(setup):
    store, now, *_ = setup
    old = command('enroll', 0)
    store.execute(old)
    now[0] += 600
    store.execute(command('enroll', 1))
    rejects('denied', lambda: store.lookup(old))


def test_lookup_cannot_change_original_authorization_scope(setup):
    store, *_ = setup
    _, result = enabled(setup)
    c = command('prove', 2, proof=result['recovery_codes'][0], **scope())
    store.execute(c)
    for change in ({'organization_id': 'other'}, {'record_id': 'other'}, {'action': 'privileged_review'}):
        rejects('denied', lambda: store.lookup(c.model_copy(update=change)))


def test_committed_retries_do_not_spend_attempt_budget(setup):
    store, now, auth, path, key = setup
    enrollment = command('enroll', 0)
    original = store.execute(enrollment)
    confirmation = command('confirm', 1, proof=core.totp(original['secret'], now[0] // 30))
    codes = store.execute(confirmation)
    for _ in range(20):
        assert store.execute(enrollment) == original
        assert store.execute(confirmation) == codes
    assert store.db.execute('SELECT count FROM attempts').fetchone()[0] == 2
    for _ in range(8):
        rejects('invalid_proof', lambda: store.execute(command('prove', 2, proof='invalid', **scope())))
    other = core.FactorStore(path, key, lambda _: auth[0], lambda: now[0])
    try:
        assert other.execute(confirmation) == codes
        rejects('conflict', lambda: other.execute(confirmation.model_copy(update={'proof': 'different'})))
        auth[0] = replace(auth[0], allowed=False)
        rejects('denied', lambda: other.execute(confirmation))
    finally:
        other.close()


def test_repository_committed_retries_bypass_limits_and_recheck_authority(setup):
    import asyncio
    from contextlib import asynccontextmanager
    from types import ModuleType

    package = ModuleType('factor_repository_package')
    package.__path__ = [str(ROOT / 'services/identity/modules/two-factor')]
    sys.modules[package.__name__] = package
    sys.modules[package.__name__ + '.core'] = core
    repository = load(package.__name__ + '.repository', 'services/identity/modules/two-factor/repository.py')
    store, _, auth, _, key = setup
    _, result = enabled(setup)
    c = command('confirm', 1, proof='unused')
    # Match the original immutable payload, whose receipt includes private codes.
    enrollment = store.lookup(command('enroll', 0))
    c = c.model_copy(update={'proof': core.totp(enrollment['secret'], setup[1][0] // 30)})
    row = store.db.execute('SELECT o.digest,o.result,f.data FROM operations o JOIN factors f '
                           'ON o.subject=f.subject WHERE o.operation=?', (c.operation_id,)).fetchone()

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetchrow(self, *_):
            return dict(zip(('digest', 'result', 'data'), row))

        async def fetchval(self, *_):
            pytest.fail('Committed retry must not charge the attempt budget')

    async def authority(_):
        return auth[0]

    async def check():
        repo = repository.Repository(Pool(), key, authority, lambda: setup[1][0])
        for _ in range(20):
            assert await repo.execute(c) == result
        with pytest.raises(core.Rejected, match='conflict'):
            await repo.execute(c.model_copy(update={'proof': 'different'}))
        auth[0] = replace(auth[0], session_id='other-session')
        with pytest.raises(core.Rejected, match='denied'):
            await repo.execute(c)
        auth[0] = replace(auth[0], allowed=False)
        with pytest.raises(core.Rejected, match='denied'):
            await repo.execute(c)
    asyncio.run(check())


def test_consumed_receipt_rechecks_producer_and_session(setup):
    store, _, auth, *_ = setup
    _, result = enabled(setup)
    proof = store.execute(command('prove', 2, proof=result['recovery_codes'][0], **scope()))
    c = command('consume', 3, proof_id=proof['proof_id'], **scope())
    store.execute(c)
    original = auth[0]
    for changed in (replace(original, protected_producer=False), replace(original, session_id='other-session')):
        auth[0] = changed
        rejects('denied', lambda: store.execute(c))
        rejects('denied', lambda: store.lookup(c))


def test_repository_consumed_receipt_rechecks_producer_and_session(setup):
    import asyncio
    from contextlib import asynccontextmanager
    from types import ModuleType

    package = ModuleType('factor_consumed_repository')
    package.__path__ = [str(ROOT / 'services/identity/modules/two-factor')]
    sys.modules[package.__name__] = package
    sys.modules[package.__name__ + '.core'] = core
    repository = load(package.__name__ + '.repository', 'services/identity/modules/two-factor/repository.py')
    store, now, auth, _, key = setup
    _, result = enabled(setup)
    proof = store.execute(command('prove', 2, proof=result['recovery_codes'][0], **scope()))
    c = command('consume', 3, proof_id=proof['proof_id'], **scope())
    consumed = store.execute(c)
    row = store.db.execute('SELECT o.digest,o.result,f.data FROM operations o JOIN factors f '
                           'ON o.subject=f.subject WHERE o.operation=?', (c.operation_id,)).fetchone()

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetchrow(self, *_):
            return dict(zip(('digest', 'result', 'data'), row))

    async def authority(_):
        return auth[0]

    async def check():
        repo = repository.Repository(Pool(), key, authority, lambda: now[0])
        assert await repo.execute(c) == consumed
        assert await repo.lookup(c) == consumed
        original = auth[0]
        for changed in (replace(original, protected_producer=False), replace(original, session_id='other-session')):
            auth[0] = changed
            for call in (repo.execute, repo.lookup):
                with pytest.raises(core.Rejected, match='denied'):
                    await call(c)
    asyncio.run(check())
