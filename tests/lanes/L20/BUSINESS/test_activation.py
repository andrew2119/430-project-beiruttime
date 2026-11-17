"""Business activation boundaries with transaction-local synthetic records."""
import ast
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import BaseModel, Field, field_validator

from test_business_policies import c

ROOT = Path(__file__).resolve().parents[4]
BUSINESS, OPERATOR, CONFIRMATION = [UUID(int=i) for i in range(20, 23)]


class PublicError(Exception):
    def __init__(self, code, message, *, status):
        self.code, self.status = code, status
        super().__init__(message)


class Tx:
    def __init__(self):
        self.receipt = None
        self.writes = []
        self.row = dict(id=BUSINESS, public_name='Synthetic business', kind='brand',
                        capabilities=['sales', 'servicing'], state='revoked',
                        revision=1, sample=False, confirmation_ref=None, confirmed_scope=[])

    async def fetchrow(self, sql, *args):
        if 'l02_business_operations' in sql:
            return self.receipt
        if 'INSERT INTO l02_businesses' in sql:
            self.writes.append((sql, args))
            self.row.update(state='active', sample=args[6], confirmation_ref=args[8],
                            confirmed_scope=args[9])
        elif 'UPDATE l02_businesses' in sql:
            self.writes.append((sql, args))
            self.row.update(state=args[1], revision=self.row['revision'] + 1)
        return self.row.copy()

    async def execute(self, sql, *args):
        if sql.startswith('INSERT'):
            self.writes.append((sql, args))
        if 'INSERT INTO l02_business_operations' in sql:
            self.receipt = dict(fingerprint=args[2], result=args[3])


def boundary(tx, permitted=True):
    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield tx

    async def current(*args, **kwargs):
        if not permitted:
            raise PermissionError()

    async def affected(*args):
        return []

    async def noop(*args):
        pass

    tree = ast.parse((ROOT / 'services/identity/modules/businesses/routes.py').read_text())
    names = {'Onboard', 'Change', 'operation', 'onboard', 'change', 'public', 'require_activation'}
    nodes = [node for node in tree.body if getattr(node, 'name', '') in names]
    for node in nodes:
        if isinstance(node, ast.AsyncFunctionDef):
            node.decorator_list = []
            node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    from typing import Literal
    namespace = dict(Contract=BaseModel, Field=Field, field_validator=field_validator,
                     Literal=Literal, UUID=UUID, uuid4=lambda: BUSINESS,
                     hashlib=hashlib, json=json, unit_of_work=transaction,
                     require_current=current, lock_accounts=noop, affected_subjects=affected,
                     sync_business=noop, require_scope=lambda *args: None,
                     PublicError=PublicError, CapabilityDeclaration=c.CapabilityDeclaration,
                     enqueue=noop, EventEnvelope=lambda **kwargs: kwargs)
    tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), '<activation-boundary>', 'exec'), namespace)
    for name in ("Onboard", "Change"):
        namespace[name].model_rebuild(_types_namespace=namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


def inputs():
    return (SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)),
                            state=SimpleNamespace(request_id='test-request')),
            SimpleNamespace(actor=SimpleNamespace(subject_id=OPERATOR)))


def onboard_body(api, **changes):
    return api.Onboard(**(dict(legal_name='Synthetic business', public_name='Synthetic business',
                              kind='brand', capabilities=['sales', 'servicing'],
                              assurance_reference='test-assurance', reason='Recorded scope confirmation') | changes))


@pytest.mark.asyncio
@pytest.mark.parametrize('confirmation,scope', [(None, []), (CONFIRMATION, ['sales']),
    (CONFIRMATION, ['sales', 'servicing', 'customization'])])
async def test_real_onboarding_denies_missing_or_different_confirmation(confirmation, scope):
    tx = Tx()
    api = boundary(tx)
    with pytest.raises(PublicError, match='تأكيد') as error:
        await api.onboard(onboard_body(api, confirmation_ref=confirmation, confirmed_scope=scope),
                          *inputs(), 'test-operation')
    assert error.value.code == 'business_confirmation_required'
    assert tx.writes == []


@pytest.mark.asyncio
async def test_confirmed_onboarding_records_scope_and_recovers_same_operation():
    tx = Tx()
    api = boundary(tx)
    body = onboard_body(api, confirmation_ref=CONFIRMATION, confirmed_scope=['sales', 'servicing'])
    result = await api.onboard(body, *inputs(), 'test-operation')
    assert result['state'] == 'active'
    insert = tx.writes[0]
    assert insert[1][8:] == (CONFIRMATION, ['sales', 'servicing'], OPERATOR)
    assert 'now()' in insert[0]
    assert 'confirmation_ref' not in result
    writes = len(tx.writes)
    assert await api.onboard(body, *inputs(), 'test-operation') == result
    assert len(tx.writes) == writes
    with pytest.raises(PublicError) as error:
        await api.onboard(body.model_copy(update={'confirmation_ref': UUID(int=99)}),
                          *inputs(), 'test-operation')
    assert error.value.code == 'idempotency_conflict'
    assert len(tx.writes) == writes
    with pytest.raises(PermissionError):
        await boundary(tx, permitted=False).onboard(body, *inputs(), 'test-operation')


@pytest.mark.asyncio
async def test_synthetic_onboarding_records_no_real_confirmation():
    tx = Tx()
    api = boundary(tx)
    await api.onboard(onboard_body(api, sample=True), *inputs(), 'test-operation')
    assert tx.writes[0][1][8:] == (None, [], None)


@pytest.mark.asyncio
@pytest.mark.parametrize('scope,allowed', [([], False), (['sales'], False), (['sales', 'servicing'], True)])
async def test_reactivation_checks_retained_exact_scope(scope, allowed):
    tx = Tx()
    tx.row.update(confirmation_ref=CONFIRMATION if scope else None, confirmed_scope=scope)
    api = boundary(tx)
    body = api.Change(revision=1, state='active', reason='Permitted reactivation')
    if allowed:
        assert (await api.change(BUSINESS, body, *inputs(), 'test-operation'))['state'] == 'active'
    else:
        with pytest.raises(PublicError):
            await api.change(BUSINESS, body, *inputs(), 'test-operation')
        assert tx.writes == []
