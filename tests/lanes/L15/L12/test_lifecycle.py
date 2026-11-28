import asyncio
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load('l12_contract', 'packages/contracts-catalog/listing-lifecycle/v1.py')
module = load('l12_lifecycle', 'services/catalog/modules/listing-lifecycle/lifecycle.py')
ID = '00000000-0000-4000-8000-000000000001'
OTHER = '00000000-0000-4000-8000-000000000002'
NEW = '00000000-0000-4000-8000-000000000003'
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def command(**changes):
    return contract.Command(**dict(dict(operation_id=ID, subject_id=ID, watch_id=ID,
        actor_id=ID, organization_id=None, expected_revision=1, kind='renew',
        proof_id='proof', quote_id='quote', quote_revision=1, policy_revision='policy'), **changes))


def source(**changes):
    return dict(dict(subject_id=ID, watch_id=ID, organization_id=None, revision=1,
        availability='unsold', payment='none', commitment='none', bid_count=0,
        winner_id=None, custody='seller', status='unsold', quote_id='quote',
        quote_revision=1, policy_revision='policy', current_terms_accepted=True,
        pricing_validated=True, facts_current=True), **changes)


def proof(**changes):
    return dict(dict(proof_id='proof', subject_id=ID, watch_id=ID, revision=1,
        issued_at=(NOW-timedelta(hours=23)).isoformat(), submitted_at=NOW.isoformat(),
        reviewed_at=NOW.isoformat(), reviewed=True, assignment_current=True,
        consumed_by=None), **changes)


def answer(c, **changes):
    return dict(dict(binding=c.payload(), state='succeeded', revision=2,
        pending_reason=None, next_actor=None, next_review_at=None,
        listing_id=NEW if c.kind == 'relist' else ID,
        auction_id=NEW, previous_auction_id=OTHER), **changes)


async def authorized(_):
    return True


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize('kind', ['pause', 'renew', 'relist'])
def test_positive(kind):
    assert module.eligibility(command(kind=kind), source(), proof(), NOW) is None


@pytest.mark.parametrize('changes', [
    {'availability': 'sold'}, {'availability': 'unknown'}, {'payment': 'unknown'},
    {'payment': 'paid_held'}, {'payment': 'declined'}, {'commitment': 'reserved'},
    {'commitment': 'job'}, {'bid_count': 1}, {'winner_id': OTHER}, {'custody': 'expert'},
])
@pytest.mark.parametrize('kind', ['pause', 'renew', 'relist'])
def test_never_break_commitment(changes, kind):
    assert module.eligibility(command(kind=kind), source(**changes), proof(), NOW) == 'committed'


@pytest.mark.parametrize('delta,valid', [(-1, True), (0, False), (1, False)])
def test_possession_submission_boundary(delta, valid):
    issued = NOW - timedelta(hours=24, seconds=1)
    submitted = issued + timedelta(hours=24, seconds=delta)
    assert module.possession_valid(proof(issued_at=issued.isoformat(),
        submitted_at=submitted.isoformat()), command(), NOW) is valid


@pytest.mark.parametrize('changes', [
    {'watch_id': OTHER}, {'subject_id': OTHER}, {'revision': 2},
    {'reviewed': False}, {'assignment_current': False}, {'consumed_by': OTHER},
    {'issued_at': (NOW+timedelta(seconds=1)).isoformat()},
    {'reviewed_at': (NOW+timedelta(seconds=1)).isoformat()},
    {'submitted_at': NOW.replace(tzinfo=None).isoformat()},
])
def test_fresh_scoped_review(changes):
    assert not module.possession_valid(proof(**changes), command(), NOW)


@pytest.mark.parametrize('changes,reason', [
    ({'revision': 2}, 'stale_revision'), ({'organization_id': OTHER}, 'ineligible'),
    ({'facts_current': False}, 'terms_changed'), ({'pricing_validated': False}, 'terms_changed'),
    ({'quote_revision': 2}, 'terms_changed'), ({'current_terms_accepted': False}, 'terms_changed'),
])
def test_current_source(changes, reason):
    assert module.eligibility(command(), source(**changes), proof(), NOW) == reason


def test_restart_and_duplicate(tmp_path):
    path = tmp_path / 'receipts.db'
    calls = []
    retained = {}

    async def transition(c):
        calls.append(c.operation_id)
        retained.setdefault(c.operation_id, answer(c))
        if len(calls) == 1:
            raise ConnectionError()
        return retained[c.operation_id]

    store = module.Store(path)
    assert run(module.Lifecycle(store, authorized, transition, responsible_operator_id=OTHER, clock=lambda: NOW).execute(command()))['state'] == 'pending'
    store.close()
    store = module.Store(path)
    lifecycle = module.Lifecycle(store, authorized, transition, responsible_operator_id=OTHER, clock=lambda: NOW)
    assert run(lifecycle.lookup(ID, ID, None))['state'] == 'pending'
    assert run(lifecycle.execute(command()))['state'] == 'succeeded'
    assert run(lifecycle.execute(command()))['revision'] == 2
    assert calls == [ID, ID]
    assert store.db.execute('SELECT count(*) FROM lifecycle_outbox').fetchone()[0] == 1
    assert 'proof' not in store.db.execute('SELECT payload FROM lifecycle_outbox').fetchone()[0]
    with pytest.raises(module.Denied):
        run(lifecycle.execute(command(kind='relist')))
    store.close()


def test_authority_rechecked_after_transition_and_on_lookup(tmp_path):
    allowed = True

    async def auth(_):
        return allowed

    async def transition(c):
        nonlocal allowed
        allowed = False
        return answer(c)

    store = module.Store(tmp_path / 'receipts.db')
    lifecycle = module.Lifecycle(store, auth, transition, responsible_operator_id=OTHER, clock=lambda: NOW)
    with pytest.raises(module.Denied):
        run(lifecycle.execute(command()))
    assert store.get(ID)[1]['state'] == 'pending'
    with pytest.raises(module.Denied):
        run(lifecycle.lookup(ID, ID, None))
    allowed = True
    with pytest.raises(module.Denied):
        run(lifecycle.lookup(ID, ID, OTHER))
    with pytest.raises(module.Denied):
        run(lifecycle.lookup(ID, OTHER, None))
    store.close()


@pytest.mark.parametrize('changes', [
    {'binding': {}}, {'revision': True}, {'revision': 1}, {'auction_id': OTHER},
    {'listing_id': OTHER}, {'extra': 'private'}, {'state': 'pending'},
])
def test_invalid_confirmation_stays_pending(tmp_path, changes):
    async def transition(c):
        return answer(c, **changes)

    store = module.Store(tmp_path / 'receipts.db')
    assert run(module.Lifecycle(store, authorized, transition, responsible_operator_id=OTHER, clock=lambda: NOW).execute(command()))['state'] == 'pending'
    assert store.db.execute('SELECT count(*) FROM lifecycle_outbox').fetchone()[0] == 0
    store.close()


def test_denial_and_new_auction_history(tmp_path):
    async def transition(c):
        return answer(c, state='denied', revision=1, pending_reason='committed',
                      listing_id=None, auction_id=None, previous_auction_id=None)

    store = module.Store(tmp_path / 'receipts.db')
    assert run(module.Lifecycle(store, authorized, transition, responsible_operator_id=OTHER, clock=lambda: NOW).execute(command()))['state'] == 'denied'
    c = command(kind='relist')
    assert module.valid_answer(c, answer(c))
    assert not module.valid_answer(c, answer(c, listing_id=ID))
    assert not module.valid_answer(c, answer(c, auction_id=OTHER))
    store.close()


def test_timeout_retains_pending(tmp_path):
    async def transition(_):
        raise TimeoutError()

    store = module.Store(tmp_path / 'receipts.db')
    assert run(module.Lifecycle(store, authorized, transition, responsible_operator_id=OTHER, clock=lambda: NOW).execute(command()))['state'] == 'pending'
    store.close()


@pytest.mark.parametrize('changes', [{'expected_revision': True}, {'expected_revision': 0},
    {'quote_revision': 1.2}, {'proof_id': None}, {'policy_revision': 'x'*129}])
def test_bounded_contract(changes):
    with pytest.raises(ValueError):
        command(**changes)


@pytest.mark.parametrize('missing', ['winner_id', 'organization_id', 'bid_count', 'payment', 'custody'])
def test_missing_source_fact_is_not_clearance(missing):
    facts = source()
    del facts[missing]
    assert module.eligibility(command(), facts, proof(), NOW) == 'ineligible'


def test_revocation_during_timeout(tmp_path):
    allowed = True

    async def auth(_):
        return allowed

    async def transition(_):
        nonlocal allowed
        allowed = False
        raise TimeoutError()

    store = module.Store(tmp_path / 'receipts.db')
    with pytest.raises(module.Denied):
        run(module.Lifecycle(store, auth, transition, responsible_operator_id=OTHER, clock=lambda: NOW).execute(command()))
    assert store.get(ID)[1]['state'] == 'pending'
    store.close()


@pytest.mark.parametrize('revision', [-1, '1', True, 1.5])
def test_pause_also_checks_supplied_quote_revision(revision):
    with pytest.raises(ValueError):
        command(kind='pause', quote_revision=revision)


def test_deterministic_contract_fixtures():
    import json
    root = ROOT / 'packages/contracts-catalog/listing-lifecycle'
    schema = json.loads((root / 'command.schema.json').read_text())
    for fixture in sorted((root / 'fixtures').glob('*.json')):
        value = json.loads(fixture.read_text())
        assert value['synthetic'] is True
        assert set(value['request']) == set(schema['required'])
        assert value['request']['schema_version'] == schema['properties']['schema_version']['const']
        c = contract.Command(**value['request'])
        assert all(value['response'][k] == v for k, v in c.payload().items())
        assert value['response']['state'] in ('succeeded', 'denied', 'pending')


@pytest.mark.parametrize('kind', ['pause', 'renew', 'relist'])
@pytest.mark.parametrize('changes', [
    {'auction_id': {'private': 'unexpected'}, 'previous_auction_id': None},
    {'auction_id': 7, 'previous_auction_id': None},
    {'previous_auction_id': []}, {'listing_id': None},
    {'next_actor': {'private': 'unexpected'}}, {'next_review_at': 'invalid'},
])
def test_complete_success_shape_stays_pending(tmp_path, kind, changes):
    async def transition(c):
        return answer(c, **changes)

    store = module.Store(tmp_path / 'receipts.db')
    assert run(module.Lifecycle(store, authorized, transition, responsible_operator_id=OTHER, clock=lambda: NOW).execute(command(kind=kind)))['state'] == 'pending'
    assert store.db.execute('SELECT count(*) FROM lifecycle_outbox').fetchone()[0] == 0
    store.close()


def test_support_assignment_survives_restart_and_overdue_retry(tmp_path):
    async def transition(_):
        raise TimeoutError()

    path = tmp_path / 'receipts.db'
    store = module.Store(path)
    service = module.Lifecycle(store, authorized, transition,
        responsible_operator_id=OTHER, clock=lambda: NOW)
    first = run(service.execute(command()))
    assert first['responsible_operator_id'] == OTHER
    assert first['next_actor'] == 'support'
    assert first['next_action'] == 'resolve_confirmation'
    assert datetime.fromisoformat(first['next_review_at']) == NOW + timedelta(hours=24)
    assert datetime.fromisoformat(first['escalate_at']) == NOW + timedelta(hours=48)
    store.close()
    store = module.Store(path)
    service = module.Lifecycle(store, authorized, transition,
        responsible_operator_id=NEW, clock=lambda: NOW + timedelta(hours=49))
    assert run(service.lookup(ID, ID, None)) == first
    assert run(service.execute(command())) == first
    store.close()
