from pathlib import Path
from uuid import UUID

import pytest
from bt_runtime.modules import discover


MODULE = next(m for m in discover(Path('services/auction/modules')) if m.id == 'L12.prebid-buy-now')
Binding = MODULE.load('recovery.py:Binding')
Resolution = MODULE.load('recovery.py:Resolution')
historical_state = MODULE.load('recovery.py:historical_state')
lookup = MODULE.load('recovery.py:lookup_resolution')
cancel = MODULE.load('recovery.py:cancel_no_bid')
Cancellation = MODULE.load('recovery.py:Cancellation')


def binding():
    return Binding(operation_id=UUID(int=1), subject_id=UUID(int=2), watch_id=UUID(int=3),
                   actor_id=UUID(int=4), organization_id=None, expected_revision=2,
                   quote_id=UUID(int=6), quote_revision=1, policy_revision=1)


def response(state):
    return {**binding().model_dump(mode='json'), 'state': state, 'revision': 2,
            'pending_reason': None, 'next_actor': str(UUID(int=5)),
            'next_review_at': '2026-11-17T00:00:00Z'}


@pytest.mark.parametrize('state,expected', [('no_attempt', 'no_attempt'), ('unknown', 'unknown'),
    ('pending', 'pending'), ('paid_held', 'paid_held'), ('declined', 'declined'), ('released', 'released')])
def test_attempt_aware_fixtures(state, expected):
    assert historical_state(binding(), response(state)) == expected


@pytest.mark.parametrize('change', [{'revision': 1}, {'revision': True}, {'revision': '2'},
    {'quote_revision': 2}, {'policy_revision': 2}, {'next_review_at': '2026-11-17T00:00:00'}, {'watch_id': str(UUID(int=8))},
    {'actor_id': str(UUID(int=8))}, {'state': 'denied'}, {'unexpected': True}, {'operation_id': str(UUID(int=8))}])
def test_stale_denied_or_mismatched_is_unavailable(change):
    assert historical_state(binding(), {**response('released'), **change}) == 'unavailable'


@pytest.mark.asyncio
async def test_lookup_lost_response_and_duplicate():
    class Provider:
        async def lookup_historical_v1(self, request):
            assert request == binding().model_dump(mode='json')
            if self.lost:
                self.lost = False
                raise TimeoutError()
            return response('no_attempt')
    provider = Provider()
    provider.lost = True
    assert (await lookup(provider, binding())) == {
        'state': 'unavailable', 'revision': None, 'pending_reason': None,
        'next_actor': None, 'next_review_at': None}
    for _ in range(2):
        assert await lookup(provider, binding()) == {key: value for key, value in
            response('no_attempt').items() if key in {
                'state', 'revision', 'pending_reason', 'next_actor', 'next_review_at'}}


@pytest.mark.asyncio
async def test_cancellation_has_no_fallback_and_retries_exact_command():
    command = Cancellation(**binding().model_dump(), scheduled_ends_at='2026-11-16T00:00:00Z')
    assert (await cancel(object(), None, command))['state'] == 'unavailable'
    class Kernel:
        calls = []
        async def cancel_no_bid_v1(self, tx, value):
            self.calls.append(value)
            if len(self.calls) == 1:
                raise TimeoutError()
            return {**binding().model_dump(mode='json'), 'state': 'denied', 'revision': 2}
    kernel = Kernel()
    assert (await cancel(kernel, None, command))['state'] == 'pending'
    assert (await cancel(kernel, None, command))['state'] == 'denied'
    assert kernel.calls[0] == kernel.calls[1]


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [None, {'state': 'cancelled'},
    {**binding().model_dump(mode='json'), 'state': 'cancelled', 'revision': 1},
    {**binding().model_dump(mode='json'), 'state': 'cancelled', 'revision': 2,
     'watch_id': str(UUID(int=9))}])
async def test_cancellation_rejects_unbound_receipts(result):
    class Kernel:
        async def cancel_no_bid_v1(self, tx, value):
            return result
    command = Cancellation(**binding().model_dump(), scheduled_ends_at='2026-11-16T00:00:00Z')
    assert (await cancel(Kernel(), None, command))['state'] == 'unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['cancelled', 'stale'])
async def test_cancellation_retains_bound_success_and_stale_replay(state):
    command = Cancellation(**binding().model_dump(), scheduled_ends_at='2026-11-16T00:00:00Z')
    receipt = {**binding().model_dump(mode='json'), 'state': state, 'revision': 2}

    class Kernel:
        def __init__(self):
            self.calls = []

        async def cancel_no_bid_v1(self, tx, value):
            self.calls.append(value)
            return dict(receipt)

    kernel = Kernel()
    for _ in range(2):
        assert await cancel(kernel, None, command) == receipt
    assert kernel.calls == [command.model_dump(mode='json')] * 2
