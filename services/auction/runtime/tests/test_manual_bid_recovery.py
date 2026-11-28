import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from bt_contracts.auction.core.models import BidCommand

from service_app import engine


@pytest.mark.parametrize('permission,expected', [(True, 'stale_revision'), (False, 'bid_permission_required')])
def test_preflight_denial_is_a_terminal_receipt_under_the_original_key(monkeypatch, permission, expected):
    auction, buyer, quote, seller = (UUID(int=index) for index in range(1, 5))
    lot = dict(id=auction, revision=4, mode='bidding', currency='USD',
               seller_id=seller, seller_organization_id=None)
    principal = SimpleNamespace(actor=SimpleNamespace(subject_id=buyer, organization_id=None), roles=['buyer'],
                                permissions=[] if permission else [engine.SUSPENDED_ACTIVITY], organizations=[])
    command = BidCommand(expected_revision=3, amount_minor=450000, fee_quote_id=quote)
    digest = engine.fingerprint('manual', auction, command)
    rows = {}
    receipts = []
    in_write = False

    class Transaction:
        async def execute(self, query, *args):
            assert in_write
            if 'advisory_xact_lock' in query:
                return
            assert 'INSERT INTO auction_operations' in query
            _, actor, organization, key, request_hash, lot_id, outcome = args
            assert (actor, organization, request_hash, lot_id) == (buyer, None, digest, auction)
            assert (actor, key) not in rows
            rows[actor, key] = dict(request_hash=digest, organization_id=None, outcome=json.loads(outcome))
            receipts.append(json.loads(outcome))

        async def fetchrow(self, query, *args):
            if 'FROM auction_operations' in query:
                return rows.get(args)
            assert 'FROM auction_lots' in query and args == (auction,)
            return lot

    @asynccontextmanager
    async def acquire():
        yield Transaction()

    @asynccontextmanager
    async def atomic(_pool):
        nonlocal in_write
        assert not in_write
        in_write = True
        try:
            yield Transaction()
        finally:
            in_write = False

    monkeypatch.setattr(engine, 'unit_of_work', atomic)
    deps = SimpleNamespace(principal=AsyncMock(return_value=principal), listing=AsyncMock(), fee=AsyncMock())
    admission = engine.AuctionEngine(deps)
    request = SimpleNamespace(headers={'idempotency-key': 'test-original'},
                              app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire))))

    async def replay():
        result = await admission.submit(request, auction, command)
        assert result['status'] == 'denied' and result['code'] == expected and result['revision'] == 4
        assert result['auction_id'] == str(auction)
        # A changed rule or restored permission cannot repurpose the old command.
        lot['revision'] = 5
        principal.permissions.clear()
        assert await admission.submit(request, auction, command) == result
        assert len(receipts) == 1
        with pytest.raises(engine.PublicError, match='idempotency_conflict'):
            await admission.submit(request, auction, command.model_copy(update={'expected_revision': 5}))

    asyncio.run(replay())
    deps.listing.assert_not_awaited()
    deps.fee.assert_not_awaited()
