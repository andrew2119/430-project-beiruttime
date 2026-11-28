"""Contact verification recovery after a committed response is lost."""
import ast
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import service_app

RUNTIME = Path(service_app.__file__).resolve().parent.parent
MODULES = RUNTIME / 'modules'
if not MODULES.is_dir():
    MODULES = RUNTIME.parent / 'modules'


class PublicError(Exception):
    def __init__(self, code, message, status):
        self.code = code
        super().__init__(message)


@pytest.mark.asyncio
async def test_committed_verification_replay_conflict_and_current_access():
    subject, challenge = UUID(int=1), UUID(int=2)
    now = datetime.now(timezone.utc)
    row = dict(consumed_at=None, expires_at=now + timedelta(minutes=10), attempts=0,
               contact_revision=1, code_digest=hashlib.sha256(f'{challenge}:123456'.encode()).hexdigest(),
               channel='email', recipient='test@example.invalid', simulated_code='123456')
    current = dict(revision=1, email='old@example.invalid', phone=None,
                   email_verified_at=now, phone_verified_at=None, email_sample=True, phone_sample=False)
    receipts, events, writes = {}, [], []
    permitted = True

    class Tx:
        async def fetchrow(self, sql, *args):
            if 'l02_contact_operations' in sql:
                return receipts.get(args)
            if 'l02_contact_challenges' in sql:
                return row
            if sql.lstrip().startswith('UPDATE l02_contacts'):
                current.update(email=args[1], revision=current['revision'] + 1)
                writes.append('contact')
            return current

        async def execute(self, sql, *args):
            if 'SET attempts=attempts+1' in sql:
                row['attempts'] += 1
            if 'SET consumed_at' in sql:
                row['consumed_at'] = args[1]
            if 'INSERT INTO l02_contact_operations' in sql:
                receipts[args[:2]] = dict(fingerprint=args[2], result=args[3])

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield Tx()

    async def live(*args, **kwargs):
        if not permitted:
            raise PermissionError()
        return {'id': subject}, None

    async def enqueue(*args):
        events.append(args)

    tree = ast.parse((MODULES / 'contacts/routes.py').read_text())
    nodes = [n for n in tree.body if getattr(n, 'name', '') in {'verify', 'digest', 'contact'}]
    for node in nodes:
        if isinstance(node, ast.AsyncFunctionDef):
            node.decorator_list = []
            node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    namespace = dict(hashlib=hashlib, hmac=hmac, json=json, datetime=datetime, timezone=timezone,
                     PublicError=PublicError, unit_of_work=transaction, live_actor=live,
                     enqueue=enqueue, EventEnvelope=lambda **kwargs: kwargs)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<contact-boundary>', 'exec'), namespace)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)), state=SimpleNamespace(request_id='test-request'))
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=subject))
    verify = namespace['verify']
    body = SimpleNamespace(code='123456')
    wrong = SimpleNamespace(code='654321')
    for _ in range(2):
        with pytest.raises(PublicError) as failure:
            await verify(challenge, wrong, request, actor, 'test-wrong-verification')
        assert failure.value.code == 'verification_failed'
    assert row['attempts'] == 1 and len(receipts) == 1
    with pytest.raises(PublicError) as conflict:
        await verify(challenge, body, request, actor, 'test-wrong-verification')
    assert conflict.value.code == 'idempotency_conflict'
    assert row['attempts'] == 1
    for attempt in range(2, 6):
        for _ in range(2):
            with pytest.raises(PublicError):
                await verify(challenge, wrong, request, actor, f'test-wrong-{attempt}')
        assert row['attempts'] == attempt
    with pytest.raises(PublicError):
        await verify(challenge, body, request, actor, 'test-exhausted')
    assert row['attempts'] == 5 and writes == events == []
    # A separate fresh challenge can still complete and recover its result.
    row['attempts'] = 0
    first = await verify(challenge, body, request, actor, 'test-verification')
    assert row['consumed_at'] is not None
    # The caller loses the first reply and replays its original immutable request.
    assert await verify(challenge, body, request, actor, 'test-verification') == first
    assert first['email'] == 'test@example.invalid' and first['revision'] == 2
    assert len(writes) == len(events) == 1
    with pytest.raises(PublicError) as conflict:
        await verify(challenge, SimpleNamespace(code='654321'), request, actor, 'test-verification')
    assert conflict.value.code == 'idempotency_conflict'
    with pytest.raises(PublicError) as consumed:
        await verify(challenge, body, request, actor, 'test-other-operation')
    assert consumed.value.code == 'verification_failed'
    permitted = False
    with pytest.raises(PermissionError):
        await verify(challenge, body, request, actor, 'test-verification')
    assert len(writes) == len(events) == 1
