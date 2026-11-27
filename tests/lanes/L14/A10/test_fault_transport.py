"""Response loss retains the real request and only interrupts the selected call."""
import asyncio
import json

import httpx
import pytest

from fault_transport import ResponseBarrier


def test_committed_response_is_held_and_replayed_unchanged():
    async def scenario():
        calls, pauses = [], []
        async def upstream(request):
            calls.append(request)
            return httpx.Response(201, json={'status': 'succeeded'})
        barrier = ResponseBarrier('http://127.0.0.1:8108',
            lambda method, path, body: method == 'POST' and body.get('subject') == 'test-auction',
            on_commit=lambda: pauses.append('paused'))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            barrier.client = client
            body = json.dumps({'subject': 'test-auction'}).encode()
            headers = {'authorization': 'Bearer test-service-token', 'idempotency-key': 'test-event'}
            pending = asyncio.create_task(barrier.forward('POST', '/internal/v1/events', headers, body))
            await asyncio.wait_for(barrier.committed.wait(), 1)
            assert not pending.done() and pauses == ['paused']
            response = await barrier.replay()
            assert response.status_code == 201
            assert len(calls) == 2 and calls[0].content == calls[1].content == body
            assert calls[0].headers['authorization'] == calls[1].headers['authorization']
            assert calls[0].headers['idempotency-key'] == calls[1].headers['idempotency-key']
            barrier.release.set()
            assert (await pending).json() == {'status': 'succeeded'}
    asyncio.run(scenario())


def test_failure_or_other_subject_does_not_arm_barrier():
    async def scenario():
        statuses = iter([503, 201])
        async def upstream(request):
            return httpx.Response(next(statuses), json={'status': 'test-outcome'})
        barrier = ResponseBarrier('http://127.0.0.1:8108',
                                   lambda method, path, body: body.get('subject') == 'test-auction')
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            barrier.client = client
            await barrier.forward('POST', '/internal/v1/events', {}, b'{"subject":"test-auction"}')
            await barrier.forward('POST', '/internal/v1/events', {}, b'{"subject":"test-other"}')
            assert not barrier.committed.is_set() and barrier.captured is None
    asyncio.run(scenario())


@pytest.mark.parametrize('url', ['http://example.test', 'https://127.0.0.1', 'http://localhost'])
def test_barrier_refuses_nonlocal_dependency(url):
    with pytest.raises(ValueError):
        ResponseBarrier(url, lambda *args: True)
