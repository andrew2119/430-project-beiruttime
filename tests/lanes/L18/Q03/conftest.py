import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

def load(name, path, package=False):
    spec = importlib.util.spec_from_file_location(name, ROOT / path,
        submodule_search_locations=[str(ROOT / path.parent)] if package else None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

# Isolate the additive contract without requiring runtime registration.
for name in ['bt_contracts', 'bt_contracts.pricing', 'bt_contracts.pricing.counteroffers']:
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
load('bt_contracts.pricing.counteroffers.current', Path('packages/contracts-pricing/counteroffers/current.py'))
load('counteroffer_module', Path('services/pricing/modules/counteroffers/__init__.py'), True)
