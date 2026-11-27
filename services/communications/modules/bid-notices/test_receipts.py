"""A committed recipient Inbox row is the availability authority."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import importlib.util
import sys
import pytest
from bt_contracts_core.errors import PublicError


def routes():
    name = 'test_bid_notice_receipts'
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name('routes.py'),
                                                submodule_search_locations=[str(Path(__file__).parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_receipt_waits_for_durable_inbox_and_scopes_every_read(monkeypatch):
    subject, auction, event, notice, inbox = [uuid4() for _ in range(5)]
    row = {'id': notice, 'auction_id': auction, 'sequence': 3}
    tx = MagicMock()
    tx.fetchrow = AsyncMock(side_effect=[row, None, row, {'id': inbox}, None])
    tx.transaction.return_value.__aenter__ = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=tx)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
    module = routes()
    monkeypatch.setattr(module, 'owner', AsyncMock(return_value=subject))
    pending = await module.notice_receipt(event, request)
    assert pending == {'event_id': str(event), 'notice_id': str(notice),
                       'auction_id': str(auction), 'sequence': 3, 'inbox_id': None}
    committed = await module.notice_receipt(event, request)
    assert committed == {**pending, 'inbox_id': str(inbox)}
    calls = tx.fetchrow.await_args_list
    assert calls[0].args[1:] == (event, subject)
    assert calls[1].args[1:] == (subject, str(notice), auction)
    with pytest.raises(PublicError) as error:
        await module.notice_receipt(event, request)
    assert error.value.status == 404
    assert module.owner.await_count == 3
