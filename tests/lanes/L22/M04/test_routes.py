from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

pytestmark = pytest.mark.asyncio
from bt_runtime.modules import Module

ROOT = Path(__file__).resolve().parents[4]
ENTRY = Module('L22.messages', ROOT/'services/communications/modules/messages', ('routes.py:router',), (), None, {}, {}, ())
router = ENTRY.load('routes.py:router')
route_module = __import__(router.routes[0].endpoint.__module__, fromlist=['actor'])
Store = ENTRY.load('domain.py:Store')


class Source:
    def __init__(self):
        self.state = 'authorized'

    async def current(self, actor, organization, thread):
        return dict(state=self.state, actor_id=actor, organization_id=organization, thread_id=thread,
                    subject_id='listing-1', watch_id='watch-1', source_revision=1, quote_revision=None,
                    policy_revision=1, current_member=True, active_support=False, paid_held=False)


def client(tmp_path, wired=True):
    app = FastAPI()
    app.include_router(router)
    async def owner():
        return SimpleNamespace(subject_id='buyer', organization_id=None)
    app.dependency_overrides[route_module.actor] = owner
    source = Source()
    if wired:
        store = Store(tmp_path/'route.db')
        store.provision(dict(id='thread-1', kind='listing', subject_id='listing-1', watch_id='watch-1',
                             organization_id=None, source_revision=1, quote_revision=None, policy_revision=1,
                             original_work_id=None, active_support=False, paid_held=False,
                             members=[dict(actor_id='buyer', joined_at='2026-01-01T00:00:00Z', left_at=None)]))
        app.state.messages_store, app.state.messages_authority = store, source
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local.test'), source, app


async def test_missing_composition_unavailable(tmp_path):
    http, _, app = client(tmp_path, False)
    response = await http.get('/v1/messages/threads/thread-1')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'source_unavailable'


async def test_adapter_send_lookup_denied_and_bounds(tmp_path):
    http, source, app = client(tmp_path)
    body = dict(operation_id='send-1', kind='send', body='Private text', expected_revision=1,
                source_revision=1, quote_revision=None, policy_revision=1)
    result = await http.post('/v1/messages/threads/thread-1/commands', json=body)
    assert result.status_code == 200
    assert (await http.get('/v1/messages/threads/thread-1/operations/send-1')).json() == result.json()
    assert (await http.post('/v1/messages/threads/thread-1/commands', json=body)).json() == result.json()
    assert (await http.get('/v1/messages/threads/thread-1?limit=51')).status_code == 422
    source.state = 'denied'
    assert (await http.get('/v1/messages/threads/thread-1')).status_code == 403
    assert (await http.get('/v1/messages/threads/thread-1/operations/send-1')).status_code == 403


async def test_actual_body_bound(tmp_path):
    http, _, app = client(tmp_path)
    assert (await http.post('/v1/messages/threads/thread-1/commands', content=b'x'*24577)).status_code == 422
    assert (await http.post('/v1/messages/threads', content=b'x'*2049)).status_code == 422


async def test_dependency_deadline(tmp_path):
    import asyncio
    http, _, app = client(tmp_path)

    async def unavailable(*args):
        await asyncio.sleep(10)

    app.state.messages_authority.current = unavailable
    start = datetime.now(timezone.utc)
    assert (await http.get('/v1/messages/threads/thread-1')).status_code == 503
    assert (datetime.now(timezone.utc)-start).total_seconds() < 3


async def test_blocked_entry_preserves_management_and_other_threads(tmp_path):
    http, source, app = client(tmp_path)
    store = app.state.messages_store

    async def snapshot(thread='thread-1'):
        authority = await source.current('buyer', None, thread)
        return dict(id=thread, kind='listing', subject_id='listing-1', watch_id='watch-1',
                    organization_id=None, source_revision=1, quote_revision=None, policy_revision=1,
                    original_work_id=None, active_support=False, paid_held=False,
                    members=[dict(actor_id=person, joined_at='2026-01-01T00:00:00Z', left_at=None)
                             for person in ('buyer', 'seller')], authority=authority)

    async def listing(*args):
        return dict(items=[await snapshot(), await snapshot('thread-2')], total=2, next_cursor=None)

    async def open_record(*args):
        return await snapshot()

    source.listing, source.open = listing, open_record
    store.provision(await snapshot())
    path = '/v1/messages/threads/thread-1'
    body = dict(operation_id='block-1', kind='block', target='seller', expected_revision=2,
                source_revision=1, quote_revision=None, policy_revision=1)
    assert (await http.post(path+'/commands', json=body)).status_code == 200
    page = await http.get('/v1/messages/threads')
    assert page.status_code == 200
    assert [item['id'] for item in page.json()['items']] == ['thread-1', 'thread-2']
    reopened = await http.post('/v1/messages/threads', json=dict(kind='listing', subject_id='listing-1'))
    assert reopened.status_code == 200
    assert 'items' not in reopened.json()
    status = await http.get(path+'/status')
    assert status.status_code == 200
    assert status.json()['blocked'] == ['seller']
    assert (await http.get(path)).status_code == 403
    assert (await http.get(path+'/operations/block-1')).json() == (await http.post(path+'/commands', json=body)).json()
    unblock = body | dict(operation_id='unblock-1', kind='unblock',
                          expected_revision=status.json()['thread']['revision'])
    receipt = await http.post(path+'/commands', json=unblock)
    assert receipt.status_code == 200
    assert (await http.post(path+'/commands', json=unblock)).json() == receipt.json()
    assert (await http.get(path)).status_code == 200

    current = source.current

    async def removed(*args):
        return await current(*args) | {'current_member': False}

    source.current = removed
    assert (await http.get('/v1/messages/threads')).status_code == 403
    assert (await http.post('/v1/messages/threads', json=dict(kind='listing', subject_id='listing-1'))).status_code == 403
    assert (await http.get(path+'/status')).status_code == 403
    source.current = current
    source.state = 'denied'
    assert (await http.get('/v1/messages/threads')).status_code == 403
    assert (await http.post('/v1/messages/threads', json=dict(kind='listing', subject_id='listing-1'))).status_code == 403
    assert (await http.get(path+'/status')).status_code == 403
