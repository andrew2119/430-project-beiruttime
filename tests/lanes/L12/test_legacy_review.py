"""Small in-memory unit checks, not real Orders release/cancellation evidence."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import json
import httpx
import pytest
from bt_bulkheads import DependencyClient
from bt_runtime.modules import discover


def load(target):
    return next(m for m in discover(Path('services/auction/modules')) if m.id == 'L12.prebid-buy-now').load(target)


def allocation():
    return {**{key: str(uuid4()) for key in ['watch_id', 'listing_id', 'buyer_id', 'quote_id']}, 'currency': 'USD', 'total_minor': 515000}


@pytest.mark.asyncio
@pytest.mark.parametrize('remote_status', [404, 503])
async def test_missing_remote_never_dispatches_an_allocation(remote_status):
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(remote_status)
    client = DependencyClient('orders', 'http://orders', timeout=.5, concurrency=1, transport=httpx.MockTransport(handle))
    deps = SimpleNamespace(clients={'orders': client}, service_headers=lambda *args: {})
    app = SimpleNamespace(state=SimpleNamespace(auction=SimpleNamespace(dependencies=deps)))
    try:
        assert await load('dependencies.py:reconcile_remote')(app, allocation(), 'prebid:stable', 'test') is None
        assert calls == [('GET', '/internal/v2/operations/prebid:stable')]
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('override', [{'currency': 'LBP'}, {'total_minor': 515001}, {'buyer_id': str(uuid4())}, {'quote_id': str(uuid4())}])
async def test_mismatched_or_legacy_success_is_not_new_payment_authority(override):
    data = allocation()
    def handle(request):
        return httpx.Response(200, json={'id': str(uuid4()), 'status': 'succeeded', 'order': {'id': str(uuid4()), **data, **override}})
    client = DependencyClient('orders', 'http://orders', timeout=.5, concurrency=1, transport=httpx.MockTransport(handle))
    app = SimpleNamespace(state=SimpleNamespace(auction=SimpleNamespace(dependencies=SimpleNamespace(clients={'orders': client}, service_headers=lambda *args: {}))))
    try:
        assert await load('dependencies.py:reconcile_remote')(app, data, 'prebid:stable', 'test') is None
    finally:
        await client.aclose()


class Transaction:
    def __init__(self, now, end):
        self.row = {'id': uuid4(), 'auction_id': uuid4(), 'lease_token': None, 'attempts': 0, 'status': 'pending',
            'allocation': allocation(), 'remote_key': 'prebid:stable', 'outcome': {'status': 'pending', 'operation_id': str(uuid4())},
            'review_state': 'outcome_pending', 'review_code': 'legacy_outcome_pending', 'scheduled_ends_at': end, 'ended_review_recorded': False}
        self.lot = {'id': self.row['auction_id'], 'listing_id': uuid4(), 'mode': 'prebid_pending', 'revision': 2, 'end_version': 1, 'ends_at': end}
        self.now = now
        self.events = []
        self.transitions = []
        self.stale_lease = False
    async def fetchrow(self, sql, *args):
        if sql.startswith('WITH due'):
            self.row.update(lease_token=args[1], attempts=self.row['attempts']+1)
            return dict(self.row)
        if self.stale_lease:
            self.row['lease_token'] = uuid4()
        return dict(self.row)
    async def execute(self, sql, *args):
        assert sql.startswith('UPDATE auction_prebid_operations')
        _, status, outcome, review, ended, delay, code = args
        self.row.update(status=status, outcome=json.loads(outcome), review_state=review, review_code=code,
            ended_review_recorded=self.row['ended_review_recorded'] or ended, lease_token=None)
    async def fetchval(self, sql): return self.now
    async def lock_lot(self, tx, auction): return self.lot
    async def server_now(self, tx): return self.now
    async def transition(self, tx, auction, **kwargs):
        self.transitions.append(kwargs)
        assert kwargs['from_mode'] == 'prebid_pending' and kwargs['to_mode'] == 'prebid_reserved'
        self.lot.update(mode='prebid_reserved', revision=self.lot['revision']+1)
        return self.lot


def wire(monkeypatch, tx, remote):
    tick = load('workers.py:tick')
    @asynccontextmanager
    async def uow(pool): yield tx
    async def reconcile(*args): return remote
    async def enqueue(connection, event, destinations): tx.events.append(event.model_dump(mode='json'))
    for name, value in {'unit_of_work': uow, 'get_kernel': lambda: tx, 'reconcile_remote': reconcile, 'enqueue': enqueue}.items():
        monkeypatch.setitem(tick.__globals__, name, value)
    return tick


@pytest.mark.asyncio
@pytest.mark.parametrize('remote,review,code', [(None, 'outcome_pending', 'legacy_outcome_pending'),
    ({'status': 'denied'}, 'release_pending', 'legacy_release_pending')])
async def test_ended_unknown_and_known_refusal_take_distinct_held_paths(monkeypatch, remote, review, code):
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    tx = Transaction(now, now-timedelta(seconds=1))
    original = dict(tx.row['allocation'])
    app = SimpleNamespace(state=SimpleNamespace(pool=object()))
    tick = wire(monkeypatch, tx, remote)
    await tick(app)
    projected = await load('routes.py:legacy_view')(tx, tx.row)
    assert tx.row['review_state'] == review and projected['code'] == code
    assert projected['financial_state'] == 'held'
    assert projected['schedule_state'] == 'ended_legacy_review'
    assert tx.row['allocation'] == original and tx.row['remote_key'] == 'prebid:stable'
    assert not tx.transitions and tx.lot['mode'] == 'prebid_pending'
    assert len(tx.events) == 1
    assert tx.row['allocation']['buyer_id'] not in json.dumps(tx.events)
    # Another worker entry after restart repeats the same held intent, without duplicate fact.
    await wire(monkeypatch, tx, remote)(app)
    assert len(tx.events) == 1 and (await load('routes.py:legacy_view')(tx, tx.row))['financial_state'] == 'held'


@pytest.mark.asyncio
async def test_historical_success_acknowledges_but_never_reopens_after_end(monkeypatch):
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    tx = Transaction(now, now)
    remote = {'status': 'succeeded', 'order': {'id': str(uuid4())}}
    await wire(monkeypatch, tx, remote)(SimpleNamespace(state=SimpleNamespace(pool=object())))
    assert tx.row['review_state'] == 'reservation_recorded'
    projected = await load('routes.py:legacy_view')(tx, tx.row)
    assert projected['status'] == 'succeeded' and projected['financial_state'] == 'held'
    assert projected['schedule_state'] == 'ended_legacy_review'
    assert tx.lot['ends_at'] == now and tx.lot['end_version'] == 1
    assert len(tx.transitions) == 1 and tx.lot['mode'] == 'prebid_reserved'


@pytest.mark.asyncio
async def test_late_conflicting_success_after_known_refusal_stays_held(monkeypatch):
    now = datetime.now(timezone.utc)
    tx = Transaction(now, now)
    tx.row.update(review_state='release_pending',review_code='legacy_release_pending',status='denied',outcome={'status':'denied','code':'reservation_denied'})
    original = dict(tx.row['outcome'])
    await wire(monkeypatch, tx, {'status': 'succeeded', 'order': {'id': str(uuid4())}})(SimpleNamespace(state=SimpleNamespace(pool=object())))
    projected = await load('routes.py:legacy_view')(tx, tx.row)
    assert projected['code'] == 'legacy_conflicting_outcome'
    assert projected['financial_state'] == 'held' and not tx.transitions
    assert tx.row['outcome'] == original  # The v1 terminal receipt is immutable.


@pytest.mark.asyncio
async def test_expired_worker_cannot_overwrite_new_claim(monkeypatch):
    now = datetime.now(timezone.utc)
    tx = Transaction(now, now)
    tx.stale_lease = True
    await wire(monkeypatch, tx, {'status': 'denied'})(SimpleNamespace(state=SimpleNamespace(pool=object())))
    assert not tx.events and tx.row['review_state'] == 'outcome_pending'


@pytest.mark.asyncio
async def test_versioned_read_uses_server_deadline_even_before_worker(monkeypatch):
    now = datetime.now(timezone.utc)
    tx = Transaction(now, now)
    async def now_read(sql): return now
    tx.fetchval = now_read
    result = await load('routes.py:legacy_view')(tx, tx.row)
    assert result['version'] == 2 and result['schedule_state'] == 'ended_legacy_review'
    assert result['financial_state'] == 'held' and result['status'] == 'pending'
