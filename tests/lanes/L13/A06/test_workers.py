import asyncio
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def worker(lane_modules, monkeypatch):
    import sys

    package = ModuleType('closing_worker_test')
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    for name, values in {
        'service': {'close': None, 'recover_assignments': None},
        'follow_up': {'escalate_overdue': None},
        'reconcile': {'Sources': None, 'reconcile': None},
    }.items():
        module = ModuleType(package.__name__ + '.' + name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return lane_modules(package.__name__ + '.workers', 'services/auction/modules/closing/workers.py')


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['allocation_pending', 'allocation_denied', 'ended_legacy_review'])
async def test_poll_assigns_existing_held_result_when_assignment_returns(
    worker, close_consumer, monkeypatch, outcome
):
    module, app, lot, state, _ = close_consumer
    app.state.closing_operator_id = None
    if outcome == 'ended_legacy_review':
        lot['mode'] = 'prebid_pending'
    await module.close(app, lot['id'], 1, 'original')
    state['row'].update(state=outcome, result_revision=1)
    if outcome == 'allocation_denied':
        state['row']['next_action'] = 'review_allocation_denial'
    original = state['row'].copy()

    async def fetch(sql):
        return []

    async def escalate(app):
        pass

    app.state.pool = SimpleNamespace(fetch=fetch)
    monkeypatch.setattr(worker, 'recover_assignments', module.recover_assignments)
    monkeypatch.setattr(worker, 'escalate_overdue', escalate)
    await worker.tick(app, None)
    assert state['row'] == original
    app.state.closing_operator_id = uuid4()
    await worker.tick(app, None)
    assigned = state['row'].copy()
    assert assigned['responsible_operator_id'] == app.state.closing_operator_id
    assert {key: value for key, value in assigned.items()
            if key not in {'responsible_operator_id', 'next_action'}} == {
        key: value for key, value in original.items()
        if key not in {'responsible_operator_id', 'next_action'}
    }
    app.state.closing_operator_id = uuid4()
    await worker.tick(app, None)
    assert state['row'] == assigned
    assert len(state['events']) == 1


@pytest.mark.asyncio
async def test_failures_do_not_block_other_closes_or_recoveries(worker, monkeypatch):
    due = [uuid4(), uuid4()]
    pending = [uuid4(), uuid4()]
    calls = []

    async def fetch(sql):
        if 'FROM auction_lots' in sql:
            return [{'id': value, 'end_version': 1} for value in due]
        return [{'auction_id': value} for value in pending]

    async def escalate(app):
        raise RuntimeError('Unavailable')

    async def close(app, subject, version, request):
        calls.append(subject)
        if subject == due[0]:
            raise RuntimeError('Unavailable')

    async def reconcile(app, sources, subject):
        calls.append(subject)
        if subject == pending[0]:
            raise RuntimeError('Unavailable')

    monkeypatch.setattr(worker, 'escalate_overdue', escalate)
    monkeypatch.setattr(worker, 'close', close)
    monkeypatch.setattr(worker, 'reconcile', reconcile)
    await worker.tick(SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(fetch=fetch))), None)
    assert calls == due + pending


@pytest.mark.asyncio
async def test_failed_poll_retries_and_closes_sources(worker, monkeypatch):
    stop = asyncio.Event()
    calls = []

    class Sources:
        def __init__(self, app):
            pass

        async def aclose(self):
            calls.append('closed')

    async def tick(app, sources):
        calls.append('tick')
        if calls.count('tick') == 1:
            raise RuntimeError('Unavailable')
        stop.set()

    async def wait_for(awaitable, timeout):
        awaitable.close()
        raise TimeoutError()

    monkeypatch.setattr(worker, 'Sources', Sources)
    monkeypatch.setattr(worker, 'tick', tick)
    monkeypatch.setattr(worker.asyncio, 'wait_for', wait_for)
    await worker.run(None, stop)
    assert calls == ['tick', 'tick', 'closed']


@pytest.mark.asyncio
async def test_persistent_failed_batch_yields_to_later_auctions_after_restart(worker, monkeypatch):
    from uuid import UUID

    due = [UUID(int=index + 1) for index in range(25)]
    retries = {}
    completed = set()
    calls = []
    now = 0

    async def fetch(sql):
        if 'FROM auction_lots' not in sql:
            return []
        assert 'INSERT INTO l13_close_delivery_retries' in sql
        assert "clock_timestamp()+interval '30 seconds'" in sql
        assert 'ON CONFLICT (auction_id) DO UPDATE' in sql
        assert 'ORDER BY r.next_attempt_at NULLS FIRST' in sql
        assert 'LIMIT 10 FOR UPDATE OF l SKIP LOCKED' in sql
        eligible = [subject for subject in due if subject not in completed
                    and retries.get(subject, 0) <= now]
        eligible.sort(key=lambda subject: (subject in retries, retries.get(subject, 0), subject))
        batch = eligible[:10]
        # Model the durable claim before any delivery.
        for subject in batch:
            retries[subject] = now + 30
        return [{'id': subject, 'end_version': 1} for subject in batch]

    async def escalate(app):
        pass

    async def close(app, subject, version, request):
        assert retries[subject] == now + 30
        assert version == 1 and request == 'close-worker'
        calls.append(subject)
        if subject in due[:10]:
            raise RuntimeError('Unavailable')
        completed.add(subject)

    monkeypatch.setattr(worker, 'escalate_overdue', escalate)
    monkeypatch.setattr(worker, 'close', close)

    def restarted_app():
        return SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(fetch=fetch)))

    await worker.tick(restarted_app(), None)
    assert calls == due[:10]
    now = 2
    await worker.tick(restarted_app(), None)
    now = 4
    await worker.tick(restarted_app(), None)
    assert completed == set(due[10:])
    assert calls == due
    now = 29
    await worker.tick(restarted_app(), None)
    assert calls == due
    now = 30
    await worker.tick(restarted_app(), None)
    assert calls == due + due[:10]
    assert completed == set(due[10:])


@pytest.mark.asyncio
async def test_cancelled_delivery_still_stops_worker(worker, monkeypatch):
    async def escalate(app):
        raise asyncio.CancelledError()

    monkeypatch.setattr(worker, 'escalate_overdue', escalate)
    with pytest.raises(asyncio.CancelledError):
        await worker.tick(None, None)
