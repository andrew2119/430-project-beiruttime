from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from bt_contracts_core.errors import AccessDenied
from bt_contracts_core.models import Actor
from bt_runtime.principal import CurrentPrincipal
from bt_runtime.modules import discover
from service_app.engine import AuctionEngine


class Reader:
    def __init__(self, lot): self.lot = lot
    def acquire(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def fetchrow(self, *args): return self.lot


@pytest.mark.asyncio
@pytest.mark.parametrize('current_owner,current_permission', [(True, True), (True, False), (False, True)])
async def test_private_reserve_rechecks_current_owner_and_permission(monkeypatch, current_owner, current_permission):
    owner = uuid4()
    now = datetime.now(timezone.utc)
    lot = {'id': uuid4(), 'seller_id': owner, 'seller_organization_id': None, 'revision': 1, 'end_version': 1,
        'starts_at': now-timedelta(minutes=1), 'ends_at': now+timedelta(minutes=1), 'accepted_sequence': 0,
        'current_minor': 0, 'reserve_minor': 450000, 'mode': 'bidding'}
    principal = CurrentPrincipal(actor=Actor(subject_id=owner if current_owner else uuid4(), session_id='unit'),
        roles=['private_seller'], permissions=['identity.listings.publish'] if current_permission else [])
    async def current(request): return principal
    async def clock(tx): return now
    handler = next(m for m in discover(Path('services/auction/modules')) if m.id == 'L12.extension-policy').load('routes.py:seller_policy')
    monkeypatch.setitem(handler.__globals__, 'get_kernel', lambda: SimpleNamespace(server_now=clock))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=Reader(lot),
        auction=SimpleNamespace(dependencies=SimpleNamespace(principal=current), owner=AuctionEngine.owner))))
    if current_owner and current_permission:
        value = await handler(lot['id'], request)
        assert value['reserve_met'] is False and value['cancellation_eligible'] is True
        assert 'reserve_minor' not in value
    else:
        with pytest.raises(AccessDenied): await handler(lot['id'], request)
