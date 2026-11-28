"""Load source contracts for lightweight unit checks, without services or a DB."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'packages/contracts-core/src'), str(ROOT / 'packages/runtime/src'),
               str(ROOT / 'packages/events/src'), str(ROOT / 'packages/bulkheads/src')]
for name, path in [('bt_contracts', ROOT / 'packages'),
                   ('bt_contracts.auction', ROOT / 'packages/contracts-auction'),
                   ('bt_contracts.pricing', ROOT / 'packages/contracts-pricing'),
                   ('bt_contracts.pricing.repair_quotes', ROOT / 'packages/contracts-pricing/repair-quotes')]:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def load(name, relative):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
sys.path.insert(0, str(ROOT / 'services/pricing/runtime'))
