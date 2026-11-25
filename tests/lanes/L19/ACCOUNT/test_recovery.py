import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('recovery', ROOT/'services/identity/modules/accounts/recovery.py')
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.mark.parametrize('locale', ['en','ar'])
def test_recovery_capture_retains_exact_token_and_language(locale):
    token = 'synthetic_single_use_token-1234567890'
    assert m.recovery_details(m.recovery_payload(token, locale)) == (token, locale)


def test_existing_encrypted_captures_keep_their_original_language():
    assert m.recovery_details('synthetic_existing_token') == ('synthetic_existing_token','en')


@pytest.mark.parametrize('payload', ['{"token":"sample","locale":"other"}', '{"token":{},"locale":"ar"}', '{"token":"sample","locale":"en","extra":true}'])
def test_invalid_capture_is_not_given_a_safe_link(payload):
    with pytest.raises(ValueError): m.recovery_details(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize('eligible', [True, False])
async def test_recovery_retry_preserves_original_message(monkeypatch, eligible):
    import copy
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import UUID
    from bt_runtime.modules import discover
    monkeypatch.syspath_prepend(str(ROOT/'services/identity/runtime'))
    routes = next(item for item in discover(ROOT/'services/identity/modules') if item.id == 'L01.accounts').load('routes.py:router')
    module = __import__(routes.routes[0].endpoint.__module__, fromlist=['recover'])

    class Store:
        def __init__(self):
            self.receipts = {}
            self.mutations = []
            self.ready = True
            self.fail = False

        async def fetchval(self, sql):
            return self.ready

        async def fetchrow(self, sql, *args):
            if 'recovery_receipts' in sql:
                return self.receipts.get(args[0])
            return {'id': UUID(int=1), 'status': 'active'} if eligible else None

        async def execute(self, sql, *args):
            if 'recovery_receipts' in sql:
                if self.fail:
                    raise OSError('interrupted')
                self.receipts[args[0]] = {'digest': args[1]}
            else:
                self.mutations.append((sql, args))

    store = Store()
    @asynccontextmanager
    async def transaction(pool, **kwargs):
        snapshot = copy.deepcopy(pool.__dict__)
        try:
            yield pool
        except BaseException:
            pool.__dict__ = snapshot
            raise

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(module, 'unit_of_work', transaction)
    monkeypatch.setattr(module, 'admission', noop)
    monkeypatch.setattr(module, 'limit', noop)
    monkeypatch.setattr(module, 'event', noop)
    monkeypatch.setattr(module, 'require_origin', lambda request: None)
    monkeypatch.setattr(module, 'private_key', lambda: 'synthetic-recovery-key')
    request = SimpleNamespace(headers={'Idempotency-Key': 'recovery-0001'}, client=SimpleNamespace(host='test'), app=SimpleNamespace(state=SimpleNamespace(pool=store)))
    body = module.Recovery(email='sample@example.test', locale='ar')
    store.fail = True
    with pytest.raises(OSError):
        await module.recover(body, request)
    assert not store.receipts and not store.mutations
    store.fail = False
    first = await module.recover(body, request)
    original = copy.deepcopy(store.__dict__)
    assert await module.recover(body, request) == first == {'accepted': True, 'delivery': 'simulated'}
    assert store.__dict__ == original
    assert len(store.mutations) == (3 if eligible else 0)
    with pytest.raises(Exception) as caught:
        await module.recover(module.Recovery(email=body.email, locale='en'), request)
    assert caught.value.code == 'operation_conflict'
    assert store.__dict__ == original
    store.ready = False
    with pytest.raises(Exception) as caught:
        await module.recover(body, request)
    assert caught.value.code == 'unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['reset', 'password'])
async def test_password_mutation_lost_response_and_bound_receipt(monkeypatch, kind):
    import copy
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import UUID
    from bt_runtime.modules import discover
    monkeypatch.syspath_prepend(str(ROOT/'services/identity/runtime'))
    router = next(item for item in discover(ROOT/'services/identity/modules') if item.id == 'L01.accounts').load('routes.py:router')
    module = __import__(router.routes[0].endpoint.__module__, fromlist=['reset'])
    subject = UUID(int=1)

    class Store:
        def __init__(self):
            self.receipt = None
            self.mutations = []
            self.used = False
            self.fail = True
            self.ready = True

        async def fetchval(self, sql, *args):
            if 'to_regclass' in sql:
                return self.ready
            if self.used:
                return None
            self.used = True
            return subject

        async def fetchrow(self, sql, *args):
            if 'password_receipts' in sql:
                return self.receipt
            return {'subject_id': subject, 'id': subject}

        async def execute(self, sql, *args):
            if 'password_receipts' in sql:
                if self.fail:
                    raise OSError('interrupted')
                self.receipt = {'digest': args[1]}
            else:
                self.mutations.append((sql, args))

    store = Store()

    @asynccontextmanager
    async def transaction(pool, **kwargs):
        assert kwargs['lock_key']
        snapshot = copy.deepcopy(pool.__dict__)
        try:
            yield pool
        except BaseException:
            pool.__dict__ = snapshot
            raise

    async def noop(*args, **kwargs):
        pass

    async def work(function, *args):
        return True if function is module.password_matches else 'encoded'

    async def actor(*args, **kwargs):
        assert not store.receipt, 'replay must not require a revoked session'
        return {'id': subject, 'password_hash': 'old'}, 'session'

    for name in ['admission', 'audit', 'event']:
        monkeypatch.setattr(module, name, noop)
    monkeypatch.setattr(module, 'unit_of_work', transaction)
    monkeypatch.setattr(module, 'password_work', work)
    monkeypatch.setattr(module, 'live_actor', actor)
    monkeypatch.setattr(module, 'require_origin', lambda request: None)
    monkeypatch.setattr(module, 'private_key', lambda: 'synthetic-recovery-key')
    request = SimpleNamespace(headers={'Idempotency-Key': 'mutation-0001', 'authorization': 'test-original-session'},
        client=SimpleNamespace(host='test'), app=SimpleNamespace(state=SimpleNamespace(pool=store)))
    body = module.Reset(token='test-'+'x'*43, password='test-new-password-1234') if kind == 'reset' else module.PasswordChange(current_password='test-old-password-1234', new_password='test-new-password-1234')
    endpoint = module.reset if kind == 'reset' else module.change_password
    with pytest.raises(OSError):
        await endpoint(body, request)
    assert not store.receipt and not store.mutations and not store.used
    store.fail = False
    assert await endpoint(body, request) == {'sign_in_required': True}
    original = copy.deepcopy(store.__dict__)
    assert await endpoint(body, request) == {'sign_in_required': True}
    assert store.__dict__ == original
    field = 'password' if kind == 'reset' else 'new_password'
    with pytest.raises(Exception) as caught:
        await endpoint(body.model_copy(update={field: 'test-different-password-123'}), request)
    assert caught.value.code == 'operation_conflict'
    if kind == 'password':
        request.headers['authorization'] = 'test-different-session'
        with pytest.raises(Exception) as caught:
            await endpoint(body, request)
        assert caught.value.code == 'operation_conflict'
    store.ready = False
    with pytest.raises(Exception) as caught:
        await endpoint(body, request)
    assert caught.value.code == 'unavailable'


@pytest.mark.asyncio
async def test_public_password_receipt_recovery_never_mutates_or_requires_session(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from bt_runtime.modules import discover
    monkeypatch.syspath_prepend(str(ROOT/'services/identity/runtime'))
    router = next(item for item in discover(ROOT/'services/identity/modules') if item.id == 'L01.accounts').load('routes.py:router')
    module = __import__(router.routes[0].endpoint.__module__, fromlist=['reset'])
    request = SimpleNamespace(headers={'Idempotency-Key': 'mutation-test-0001'}, client=SimpleNamespace(host='test'))
    original = module.PasswordChange(current_password='test-old-password-1234', new_password='test-new-password-1234')
    body = module.PasswordReceipt(**original.model_dump(), action='password_receipt', authorization='test-original-authorization')
    request.app = SimpleNamespace(state=SimpleNamespace(pool=None))
    @asynccontextmanager
    async def transaction(*args, **kwargs): yield None
    async def noop(*args, **kwargs): pass
    present = False
    async def replay(tx, key, signature):
        bound_request = SimpleNamespace(headers={'Idempotency-Key':'mutation-test-0001', 'authorization':body.authorization})
        assert (key, signature) == module.mutation_reference(bound_request, 'password', original)
        return present
    monkeypatch.setattr(module, 'unit_of_work', transaction)
    monkeypatch.setattr(module, 'admission', noop)
    monkeypatch.setattr(module, 'require_origin', lambda request: None)
    monkeypatch.setattr(module, 'mutation_replay', replay)
    monkeypatch.setattr(module, 'private_key', lambda: 'test-recovery-secret')
    with pytest.raises(Exception) as caught:
        await module.reset(body, request)
    assert caught.value.code == 'operation_pending'
    present = True
    assert await module.reset(body, request) == {'sign_in_required': True}
