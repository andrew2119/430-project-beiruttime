"""Load module contracts without starting services."""
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / path) for path in (
    'packages/contracts-core/src', 'packages/runtime/src',
    'packages/events/src', 'packages/bulkheads/src')]
for name, relative in (
    ('bt_contracts', 'packages'), ('bt_contracts.pricing', 'packages/contracts-pricing'),
    ('service_app', 'services/pricing/runtime/service_app'),
    ('price_quotes', 'services/pricing/modules/quotes'),
):
    module = types.ModuleType(name)
    module.__path__ = [str(ROOT / relative)]
    sys.modules[name] = module


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
