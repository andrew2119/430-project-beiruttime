"""Execute the read boundaries with deterministic transaction records."""
import ast
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[4]
SUBJECT = UUID(int=1)


class Denied(Exception):
    pass


class Tx:
    def __init__(self):
        self.calls = []
        self.total = 1000
        self.rows = []
        self.row = None

    async def execute(self, sql, *args):
        self.calls.append((sql, args))

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return self.total

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows

    async def fetchrow(self, sql, *args):
        return self.row


def boundary(module, names, tx, *, permitted=True):
    @asynccontextmanager
    async def transaction(pool):
        assert pool is tx
        yield tx

    async def current(*args, **kwargs):
        if not permitted:
            raise Denied()

    async def application(*args):
        return {"revision": 4}

    tree = ast.parse((ROOT / f"services/identity/modules/{module}/routes.py").read_text())
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    for node in functions:
        node.decorator_list = []
        node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    namespace = dict(unit_of_work=transaction, require_current=current, live_actor=current,
                     assert_business=current, require_scope=lambda *args: None,
                     dto=dict, public=dict, AccessDenied=Denied, application=application)
    tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *functions], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), '<read-boundary>', 'exec'), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


def inputs(tx, *, platform=True):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=tx)))
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=SUBJECT),
                            permissions=['identity.membership.manage'] if platform else [])
    return request, actor


@pytest.mark.asyncio
@pytest.mark.parametrize('total', [0, 1, 1000])
async def test_directory_pages_and_complete_counts(total):
    tx = Tx()
    tx.total = total
    tx.rows = [{"id": str(index)} for index in range(min(total, 25))]
    reads = boundary('businesses', ['directory_v2', 'records_v2'], tx)
    request, actor = inputs(tx)
    for invoke in [lambda: reads.directory_v2(request, 1, 25),
                   lambda: reads.records_v2(request, actor, 1, 25)]:
        result = await invoke()
        assert result == dict(items=tx.rows, total=total, page=1, page_size=25)
    assert all('id LIMIT' in sql for sql, _ in tx.calls if sql.startswith('SELECT *'))


@pytest.mark.asyncio
async def test_private_reads_fail_closed_and_scope_pages():
    for module, name in [('businesses', 'records_v2'), ('membership', 'members_v2')]:
        tx = Tx()
        reads = boundary(module, [name], tx, permitted=False)
        request, actor = inputs(tx)
        with pytest.raises(Denied):
            if module == 'businesses':
                await reads.records_v2(request, actor, 1, 25)
            else:
                await reads.members_v2(SUBJECT, request, actor, 1, 25)
        assert not any(sql.startswith('SELECT') for sql, _ in tx.calls)
    tx = Tx()
    reads = boundary('membership', ['members_v2'], tx)
    request, actor = inputs(tx)
    result = await reads.members_v2(SUBJECT, request, actor, 2, 25)
    assert result['total'] == 1000 and result['page'] == 2
    assert tx.calls[-1][1] == (SUBJECT, 25, 25)
    assert 'business_id=$1 ORDER BY id' in tx.calls[-1][0]


@pytest.mark.asyncio
@pytest.mark.parametrize('own', [True, False])
async def test_review_scope_and_current_permission(own):
    tx = Tx()
    reads = boundary('private-review', ['review_page'], tx)
    request, actor = inputs(tx)
    assert (await reads.review_page(request, actor, 40, 25, own=own))['total'] == 1000
    sql, args = tx.calls[-1]
    assert ('applicant_id=$1' if own else 'reviewer_id=$1') in sql
    assert args == (SUBJECT, 25, 975)
    denied = boundary('private-review', ['review_page'], tx, permitted=False)
    with pytest.raises(Denied):
        await denied.review_page(request, actor, 1, 25, own=own)


@pytest.mark.asyncio
async def test_history_bounded_cursor_total_and_reassignment_denial():
    tx = Tx()
    tx.row = dict(id=SUBJECT, applicant_id=SUBJECT, reviewer_id=UUID(int=2), application_id=UUID(int=3))
    tx.rows = [dict(revision=revision) for revision in range(50, 24, -1)]
    reads = boundary('private-review', ['detail_v2'], tx)
    request, actor = inputs(tx)
    result = await reads.detail_v2(SUBJECT, request, actor, 51)
    assert result['history_total'] == 1000
    assert len(result['history']) == 25
    assert result['history_before_revision'] == 26
    tx.row['applicant_id'] = UUID(int=4)
    with pytest.raises(Denied) as denial:
        await reads.detail_v2(SUBJECT, request, actor, 51)
    assert str(denial.value) == (
        "Only the applicant or currently assigned reviewer may read the review. / "
        "لا يمكن قراءة المراجعة إلا لمقدم الطلب أو المراجع المعيّن حاليًا."
    )
    assert 'LIMIT 26' in tx.calls[1][0]
    actor.actor.subject_id = UUID(int=9)
    with pytest.raises(Denied):
        await reads.detail_v2(SUBJECT, request, actor, None)


@pytest.mark.asyncio
async def test_timeout_does_not_return_empty_page():
    tx = Tx()

    async def timeout(*args):
        raise TimeoutError()

    tx.fetchval = timeout
    reads = boundary('businesses', ['directory_v2'], tx)
    request, _ = inputs(tx)
    with pytest.raises(TimeoutError):
        await reads.directory_v2(request, 1, 25)
