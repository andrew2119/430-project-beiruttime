"""Isolated import boundaries for focused payment checks."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def modules(monkeypatch):
    for name, path in [('bt_contracts', 'packages'), ('bt_contracts.orders', 'packages/contracts-orders'),
                       ('service_app', 'services/orders/runtime/service_app')]:
        module = ModuleType(name)
        module.__path__ = [str(ROOT / path)]
        monkeypatch.setitem(sys.modules, name, module)
    before = set(sys.modules)

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    yield load
    for name in set(sys.modules) - before:
        if name.startswith(('bt_contracts.', 'service_app.')):
            sys.modules.pop(name, None)
