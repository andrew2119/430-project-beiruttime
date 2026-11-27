"""Import only this lane's modules; no runtime boot, database or services."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def lane_modules(monkeypatch):
    def namespace(name, relative):
        module = ModuleType(name)
        module.__path__ = [str(ROOT / relative)]
        monkeypatch.setitem(sys.modules, name, module)

    namespace("bt_contracts", "packages")
    namespace("bt_contracts.orders", "packages/contracts-orders")
    namespace("bt_contracts.auction", "packages/contracts-auction")
    namespace("bt_contracts.pricing", "packages/contracts-pricing")
    namespace("service_app", "services/orders/runtime/service_app")
    namespace("l13_payment_module", "services/orders/modules/payments")

    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    # Mark imported children for restoration too: each test has fresh modules.
    before = set(sys.modules)
    yield load
    for name in set(sys.modules) - before:
        if name.startswith(("service_app.", "bt_contracts.", "l13_payment_module.")):
            sys.modules.pop(name, None)
