from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from bt_contracts.auction.policy.models import PrebidCommand
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.modules import discover


def load(target):
    return next(m for m in discover(Path('services/auction/modules')) if m.id == 'L12.prebid-buy-now').load(target)


class ReadPool:
    def __init__(self, row=None): self.row = row
    def acquire(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def fetchrow(self, sql, subject, key): return self.row


def context(row=None, roles=None, organization=None):
    principal = SimpleNamespace(roles=roles or ['buyer'], actor=SimpleNamespace(subject_id=uuid4(), organization_id=organization))
    async def current(request): return principal
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=ReadPool(row),
        auction=SimpleNamespace(dependencies=SimpleNamespace(principal=current)))), headers={'idempotency-key': 'stable'})


@pytest.mark.asyncio
async def test_new_auction_purchase_refuses_without_kernel_or_upstream_calls():
    request = context()
    with pytest.raises(PublicError) as error:
        await load('routes.py:purchase')(uuid4(), PrebidCommand(expected_revision=1, quote_id=uuid4()), request)
    assert error.value.code == 'auction_purchase_removed'


@pytest.mark.asyncio
async def test_exact_historical_replay_survives_restart_without_new_commitment():
    from service_app.engine import fingerprint
    auction = uuid4()
    command = PrebidCommand(expected_revision=1, quote_id=uuid4())
    outcome = {'status': 'pending', 'operation_id': str(uuid4()), 'auction_id': str(auction)}
    row = {'request_hash': fingerprint('prebid', auction, command), 'outcome': outcome}
    # Two independent request contexts stand for a lost response and a restarted reader.
    for request in [context(row), context(row)]:
        assert await load('routes.py:purchase')(auction, command, request) == outcome
    with pytest.raises(PublicError) as error:
        await load('routes.py:purchase')(auction, PrebidCommand(expected_revision=2, quote_id=command.quote_id), context(row))
    assert error.value.code == 'idempotency_conflict'


@pytest.mark.asyncio
async def test_business_actor_cannot_replay_private_buyer_operations():
    with pytest.raises(AccessDenied):
        await load('routes.py:purchase')(uuid4(), PrebidCommand(expected_revision=1, quote_id=uuid4()), context(organization=uuid4()))


def test_frontend_gateway_has_only_historical_reads():
    source = Path('web/registrations/L12.ts').read_text()
    assert '/prebid-buy-now\'' not in source and 'auction-quotes' not in source
    assert '/my-prebid' in source and '/prebid-operations/:key' in source
    assert "methods:['PATCH']" not in source
