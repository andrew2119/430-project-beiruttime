import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from service_app import first_bid


@pytest.mark.parametrize('already_committed', [False, True])
def test_retired_command_cannot_commit_a_first_bid_fence(monkeypatch, already_committed):
    auction, buyer, watch, listing = (UUID(int=index) for index in range(1, 5))
    principal = SimpleNamespace(actor=SimpleNamespace(subject_id=buyer, organization_id=None))
    lot = dict(id=auction, watch_id=watch, listing_id=listing, listing_revision=2, revision=3,
               first_bid_confirmed=False, accepted_sequence=0, mode='bidding')
    receipt = dict(auction_id=auction, request_hash='exact-command', organization_id=None,
                   outcome=dict(status='denied', code='legacy_maximum_retired'))
    locks = 0

    class Transaction:
        async def execute(self, sql, *args):
            assert 'pg_advisory_xact_lock' in sql, 'A terminal receipt must cause no write'

        async def fetchrow(self, sql, *args):
            nonlocal locks
            if 'FROM auction_operations' in sql:
                assert args == (buyer, 'test-original')
                locks += 1
                return None if locks == 1 else receipt
            assert locks == 1, 'No aggregate access after finding the terminal receipt'
            if 'FROM auction_lots' in sql:
                return lot
            assert 'FROM auction_first_bid_intents' in sql
            return None

    @asynccontextmanager
    async def transaction(pool):
        yield Transaction()

    monkeypatch.setattr(first_bid, 'unit_of_work', transaction)
    dependencies = SimpleNamespace(fence_state=AsyncMock(return_value=dict(
        watch_id=str(watch), listing_id=str(listing), source_id=str(auction), status='fenced',
        api_version=2, listing_revision=2, revision=5, auction_committed=already_committed)),
        json=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    asyncio.run(first_bid.prepare(request, dependencies, auction, principal, 'test-original', 'exact-command',
                                  fee_expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc)))
    assert locks == 2
    dependencies.fence_state.assert_awaited_once()
    dependencies.json.assert_not_awaited()
