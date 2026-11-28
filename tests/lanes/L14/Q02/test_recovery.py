import asyncio
import builtins
import runpy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

UNIT = Path(__file__).resolve().parents[1] / 'unit'

def load_offer_terms():
    setup = runpy.run_path(str(UNIT / 'conftest.py'))
    sibling = SimpleNamespace(ROOT=setup['ROOT'], load=setup['load'])

    def import_for_terms(name, globals=None, locals=None, fromlist=(), level=0):
        # Bind the sibling's bare import locally; never read or replace sys.modules['conftest'].
        if level == 0 and name == 'conftest':
            return sibling
        return builtins.__import__(name, globals, locals, fromlist, level)

    names = runpy.run_path(str(UNIT / 'test_offer_terms.py'),
                           init_globals={'__builtins__': dict(vars(builtins), __import__=import_for_terms)})
    return SimpleNamespace(**names)


base = load_offer_terms()
routes, closure = base.routes, base.closure


def orders_success(command, *, order_id=UUID(int=99), **order_changes):
    return {'id': str(UUID(int=101)), 'request_id': 'q02-test', 'status': 'succeeded',
            'resource_id': str(order_id), 'order': {**command, 'id': str(order_id), **order_changes}}


def test_physical_commitment_closes_other_listing_references():
    fact = {'watch_id': str(base.WATCH), 'listing_id': str(UUID(int=99)),
            'listing_revision': 1, 'status': 'reserved'}
    assert closure.committed(fact, base.row())
    assert not closure.committed({**fact, 'status': 'unknown'}, base.row())
    assert not closure.committed({**fact, 'watch_id': str(UUID(int=100))}, base.row())
    assert not closure.committed({**fact, 'listing_id': 'not-a-listing-id'}, base.row())
    assert not closure.committed({**fact, 'listing_id': str(base.LISTING), 'listing_revision': 0}, base.row())


@pytest.mark.parametrize('revision', [False, True, 0, -1, '1', 1.0, None])
@pytest.mark.parametrize('listing_id', [base.LISTING, UUID(int=99)])
def test_commitment_requires_a_positive_integer_revision(revision, listing_id):
    fact = {'watch_id': str(base.WATCH), 'listing_id': str(listing_id),
            'listing_revision': revision, 'status': 'reserved'}
    assert not closure.committed(fact, base.row())


def test_block_replay_rechecks_current_party(monkeypatch):
    db, request = base.setup(monkeypatch)
    async def replay(*args):
        return {'status': 'succeeded'}
    monkeypatch.setattr(routes, 'replay', replay)
    principal = base.CurrentPrincipal(actor={'subject_id': UUID(int=99), 'session_id': 'unit'}, roles=['buyer'])
    with pytest.raises(routes.AccessDenied):
        asyncio.run(routes.set_block(base.OFFER, request, principal, 'same-block', remove=True))


@pytest.mark.parametrize('field', ['watch_id', 'listing_id', 'buyer_id', 'quote_id', 'currency', 'total_minor'])
def test_mismatched_success_remains_pending(monkeypatch, field):
    db, request = base.setup(monkeypatch)
    command = {'operation_key': 'offer:one', 'watch_id': str(base.WATCH), 'listing_id': str(base.LISTING),
               'buyer_id': str(base.BUYER), 'quote_id': str(base.QUOTE), 'quote_revision': 1, 'currency': 'USD', 'total_minor': 515000}
    db.offer.update(state='acceptance_pending', orders_command=command)
    async def call(*args, **kwargs):
        return orders_success(command, **{field: 'wrong'})
    monkeypatch.setattr(base.peers, 'call', call)
    result = asyncio.run(routes.reconcile_intent(request, base.OFFER))
    assert result['status'] == 'pending'
    assert db.offer['state'] == 'acceptance_pending'
    assert not any('UPDATE l14_offers' in sql for sql, _ in db.executed)


@pytest.mark.parametrize('offset,allowed', [(-1, False), (0, False), (1, True)])
def test_acceptance_deadline_boundary(monkeypatch, offset, allowed):
    from datetime import timedelta
    db, request = base.setup(monkeypatch)
    db.offer['expires_at'] = base.NOW + timedelta(seconds=offset)
    principal = base.CurrentPrincipal(actor={'subject_id': base.SELLER, 'session_id': 'unit'},
                                      roles=['private_seller'], permissions=['identity.listings.publish'])
    async def reconcile(*args):
        pass
    monkeypatch.setattr(routes, 'reconcile', reconcile)
    action = routes.answer(base.OFFER, base.AnswerOffer(expected_revision=1, action='accept'),
                           request, principal, 'deadline')
    if allowed:
        assert routes.decoded(asyncio.run(action))['status'] == 'pending'
    else:
        with pytest.raises(base.PublicError):
            asyncio.run(action)
        assert db.offer['state'] == 'open'


@pytest.mark.parametrize('physical', [False, True])
def test_cross_route_closure_notifies_once(monkeypatch, physical):
    from contextlib import asynccontextmanager
    db, request = base.setup(monkeypatch)
    notices = []
    async def fetch(sql, *args):
        assert '($3 OR listing_id=$2)' in sql
        assert routes.CURRENT_TERMS in sql
        assert args == (base.WATCH, base.LISTING, physical)
        if db.offer['state'] != 'open':
            return []
        db.offer.update(state='closed', revision=2)
        return [db.offer]
    db.fetch = fetch
    @asynccontextmanager
    async def uow(*args, **kwargs):
        yield db
    async def notice(*args):
        notices.append(args[-1])
    async def call(_request, service, *_args, **_kwargs):
        if service == 'orders':
            return {'watch_id': str(base.WATCH), 'listing_id': str(UUID(int=99)),
                    'listing_revision': 1, 'status': 'reserved' if physical else 'unknown'}
        assert service == 'catalog' and not physical
        return {'id': str(base.LISTING), 'status': 'withdrawn', 'revision': 1}
    monkeypatch.setattr(closure, 'unit_of_work', uow)
    monkeypatch.setattr(closure, 'notice', notice)
    monkeypatch.setattr(base.peers, 'call', call)
    assert asyncio.run(closure.close_other_route(request, db.offer)) == 1
    assert asyncio.run(closure.close_other_route(request, db.offer)) == 0
    assert notices == ['closed']


@pytest.mark.parametrize('response', [None, [], 'unknown', {**orders_success({}), 'order': None},
                                     orders_success({}, id=123)])
def test_malformed_lookup_remains_pending(monkeypatch, response):
    db, request = base.setup(monkeypatch)
    command = {'operation_key': 'offer:one'}
    db.offer.update(state='acceptance_pending', orders_command=command)
    calls = []
    async def call(*args, **kwargs):
        calls.append((args, kwargs))
        return response
    monkeypatch.setattr(base.peers, 'call', call)
    assert asyncio.run(routes.reconcile_intent(request, base.OFFER))['status'] == 'pending'
    if response is None:
        assert len(calls) == 2
        assert calls[1][0][2] == 'POST'
        assert calls[1][1]['json'] == command
        assert calls[1][1]['headers'] == {'Idempotency-Key': 'offer:one'}


@pytest.mark.parametrize('status,state', [('succeeded', 'accepted'), ('denied', 'lost')])
def test_reconciliation_records_one_terminal_result(monkeypatch, status, state):
    db, request = base.setup(monkeypatch)
    command = {'operation_key': 'offer:one', 'watch_id': str(base.WATCH), 'listing_id': str(base.LISTING),
               'buyer_id': str(base.BUYER), 'quote_id': str(base.QUOTE), 'quote_revision': 1, 'currency': 'USD', 'total_minor': 515000}
    db.offer.update(state='acceptance_pending', orders_command=command, acceptance_operation_id=UUID(int=100))
    notices = []
    original = db.fetchrow
    async def fetchrow(sql, *args):
        if 'SET state=$2' in sql:
            db.offer.update(state=args[1], orders_result=args[2], revision=2)
        return await original(sql, *args)
    async def fetch(sql, *args):
        assert 'WHERE watch_id=$1' in sql
        assert routes.CURRENT_TERMS in sql
        assert args == (base.WATCH, base.OFFER)
        return [{**db.offer, 'id': UUID(int=99), 'state': 'closed'}]
    async def call(*args, **kwargs):
        return orders_success(command) if status == 'succeeded' else {'status': 'denied'}
    async def notice(tx, request, row, kind):
        notices.append(kind)
    db.fetchrow, db.fetch = fetchrow, fetch
    monkeypatch.setattr(base.peers, 'call', call)
    monkeypatch.setattr(routes, 'notice', notice)
    for _ in range(2):
        result = asyncio.run(routes.reconcile_intent(request, base.OFFER))
        assert result['status'] == status
        assert result['offer']['state'] == state
    assert notices == ([state, 'closed'] if status == 'succeeded' else [state])


@pytest.mark.parametrize('revision', [2, None, True, '1'])
def test_quote_revision_evidence_required(monkeypatch, revision):
    db, request = base.setup(monkeypatch)
    command = {'operation_key': 'offer:one', 'watch_id': str(base.WATCH),
               'listing_id': str(base.LISTING), 'buyer_id': str(base.BUYER),
               'quote_id': str(base.QUOTE), 'quote_revision': 1,
               'currency': 'USD', 'total_minor': 515000}
    db.offer.update(state='acceptance_pending', orders_command=command)
    success = orders_success(command, quote_revision=revision)
    if revision is None:
        del success['order']['quote_revision']
    async def call(*args, **kwargs):
        return success
    monkeypatch.setattr(base.peers, 'call', call)
    result = asyncio.run(routes.reconcile_intent(request, base.OFFER))
    assert result['status'] == 'pending'
    assert result['code'] == 'reservation_unknown'
    assert db.offer['state'] == 'acceptance_pending'
    assert db.offer['revision'] == 1
    assert db.offer['orders_command'] == command
    assert all(sql.startswith('SELECT ') for sql, _ in db.executed)


@pytest.mark.parametrize('bad_fields', [
    {'resource_id': str(UUID(int=100))}, {'resource_id': None}, {'id': 'not-an-operation-id'}, {'request_id': ''},
])
def test_bad_success_envelope_does_not_open_write_transaction(monkeypatch, bad_fields):
    db, request = base.setup(monkeypatch)
    command = {'operation_key': 'offer:one', 'watch_id': str(base.WATCH),
               'listing_id': str(base.LISTING), 'buyer_id': str(base.BUYER),
               'quote_id': str(base.QUOTE), 'quote_revision': 1, 'currency': 'USD', 'total_minor': 515000}
    db.offer.update(state='acceptance_pending', orders_command=command)

    async def call(*args, **kwargs):
        return {**orders_success(command), **bad_fields}

    def no_write(*args, **kwargs):
        pytest.fail('A malformed success opened a write transaction')

    monkeypatch.setattr(base.peers, 'call', call)
    monkeypatch.setattr(routes, 'unit_of_work', no_write)
    result = asyncio.run(routes.reconcile_intent(request, base.OFFER))
    assert result['status'] == 'pending' and result['code'] == 'reservation_unknown'
    assert db.offer['state'] == 'acceptance_pending' and db.offer['revision'] == 1
    assert db.offer['orders_command'] == command
