"""Owner receipt reads disclose only the current buyer's committed source event."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import importlib.util
import pytest
from bt_contracts_core.errors import PublicError


def routes():
    spec = importlib.util.spec_from_file_location('bid_receipt_routes', Path(__file__).with_name('routes.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_source_receipt_is_scoped_and_redacted():
    subject, auction, event = uuid4(), uuid4(), uuid4()
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value={'event_id': event}))
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=tx)
    principal = SimpleNamespace(actor=SimpleNamespace(subject_id=subject, organization_id=None))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool,
        auction=SimpleNamespace(dependencies=SimpleNamespace(principal=AsyncMock(return_value=principal))))))
    read = routes().bid_receipt
    assert await read(auction, 3, request) == {
        'event_id': str(event), 'auction_id': str(auction), 'sequence': 3}
    assert tx.fetchrow.await_args.args[1:] == (str(auction), '3', str(subject))
    tx.fetchrow.return_value = None
    with pytest.raises(PublicError) as error:
        await read(auction, 3, request)
    assert error.value.status == 404


@pytest.mark.asyncio
async def test_deadline_boundary_uses_stored_deadline_and_current_seller():
    from datetime import datetime, timezone
    subject, auction = uuid4(), uuid4()
    deadline = datetime(2026, 11, 17, tzinfo=timezone.utc)
    lot = {'seller_id': subject, 'ends_at': deadline, 'starts_at': deadline,
           'mode': 'bidding', 'revision': 1, 'accepted_sequence': 0}
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value=lot))
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=tx)
    actor = SimpleNamespace(subject_id=subject, organization_id=None)
    principal = SimpleNamespace(actor=actor)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool,
        auction=SimpleNamespace(dependencies=SimpleNamespace(principal=AsyncMock(return_value=principal))))))
    read = routes().deadline_boundary
    result = await read(auction, request)
    assert result['ends_at'] == result['evaluated_at'] == deadline.isoformat()
    assert result['code'] == 'auction_ended'
    actor.subject_id = uuid4()
    with pytest.raises(PublicError) as error:
        await read(auction, request)
    assert error.value.status == 404
