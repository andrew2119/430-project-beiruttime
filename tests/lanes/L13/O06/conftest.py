"""Isolated contract imports without starting services."""
import sys
from pathlib import Path
from types import ModuleType
import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def modules(monkeypatch):
    for name, relative in [('bt_contracts', 'packages'), ('bt_contracts.orders', 'packages/contracts-orders'),
                           ('cancellations', 'services/orders/modules/cancellations')]:
        module = ModuleType(name)
        module.__path__ = [str(ROOT / relative)]
        monkeypatch.setitem(sys.modules, name, module)
    from bt_contracts.orders.cancellations import v1
    from cancellations import policy, service
    yield v1, policy, service
    for name in list(sys.modules):
        if name.startswith(('bt_contracts.orders.cancellations', 'cancellations.')):
            sys.modules.pop(name, None)
